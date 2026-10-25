#!/usr/bin/env python3
"""Run one bounded, opt-in owned marketing turn.

The runner owns orchestration only.  It never sends mail, posts to a provider,
spends money, or bypasses the existing review and publication workflows.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path("/home/agency")
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/owned_marketing.json"
STATE = Path("/home/agency/.local/state/agency-os/owned-marketing")
OPERATOR_ROOT = Path("/home/agency/.local/share/agency-marketing/operators")
RAW_SECRET_NAMES = tuple({"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "ZAI_API_KEY", "OPENROUTER_API_KEY"})
SAFE_STATUS = {"waiting_children", "running", "done", "failed"}


def load_env(path: Path = Path("/home/agency/.config/agency/core.env")) -> dict[str, str]:
    values = dict(os.environ)
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values.setdefault(key.strip(), value.strip().strip("\"'"))
    except OSError:
        pass
    return values


def clean_env(values: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(values or os.environ)
    safe = {"PATH", "HOME", "CODEX_HOME", "NO_COLOR", "LANG", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
    return {k: v for k, v in env.items() if k in safe or k.startswith("LC_")} | {
        "HOME": "/home/agency", "CODEX_HOME": "/home/agency/.codex", "NO_COLOR": "1",
        "PATH": env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    }


def redact(value: str, secrets: list[str] | None = None) -> str:
    text = value or ""
    for secret in secrets or []:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,}]+", r"\1=[REDACTED]", text)
    return text


def read_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read marketing config: {type(exc).__name__}") from None
    if not isinstance(config, dict) or config.get("schema_version", config.get("schema")) != 1:
        raise ValueError("owned marketing config schema must be 1")
    brands = config.get("brands")
    if not isinstance(brands, dict):
        raise ValueError("config.brands must be an object")
    config["_config_path"] = str(path)
    return config


def brand_config(config: dict[str, Any], brand_id: int) -> dict[str, Any]:
    item = config.get("brands", {}).get(str(brand_id))
    if not isinstance(item, dict) or item.get("enabled") is not True:
        raise ValueError(f"brand {brand_id} is not enabled")
    prompt_file = Path(str(item.get("prompt_file", ""))).expanduser()
    if not prompt_file.is_absolute():
        config_dir = Path(config.get("_config_path", ROOT / "config")).parent
        prompt_file = config_dir / prompt_file
        if not prompt_file.is_file():
            prompt_file = config_dir.parent / Path(str(item.get("prompt_file", "")))
    if not prompt_file.is_file():
        raise ValueError("configured prompt file is missing")
    timeout = int(item.get("timeout_seconds", config.get("timeout_seconds", 1800)))
    if timeout < 60 or timeout > 3600:
        raise ValueError("timeout_seconds must be between 60 and 3600")
    workdir = Path(str(item.get("workdir", OPERATOR_ROOT / str(brand_id)))).expanduser().resolve()
    if workdir != OPERATOR_ROOT / str(brand_id):
        raise ValueError("workdir must be within the marketing operator root")
    return {**item, "prompt_file": prompt_file, "timeout_seconds": timeout, "workdir": workdir}


def connect(env: dict[str, str]):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(
        host=env.get("POSTGRES_HOST", "100.64.0.1"),
        port=int(env.get("POSTGRES_PORT", "5432")),
        dbname=env.get("POSTGRES_DB", "agencyos"),
        user=env.get("POSTGRES_USER", "agency"),
        password=env.get("POSTGRES_PASSWORD", ""), cursor_factory=RealDictCursor,
    )


def active_brand(conn, brand_id: int, project_id: int | None = None) -> bool:
    with conn.cursor() as cur:
        cur.execute("""SELECT b.id,b.project_id FROM brands b LEFT JOIN projects p ON p.id=b.project_id
                       WHERE b.id=%s AND (b.project_id IS NULL OR p.lifecycle='active')""", (brand_id,))
        row = cur.fetchone()
        if row is None: return False
        actual = row.get("project_id") if isinstance(row, dict) else row[1]
        return project_id is None or actual == project_id


def existing_today(conn, brand_id: int, day: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("""SELECT id,status,created_at,params FROM tasks
                       WHERE type='owned_marketing_run' AND params->>'brand_id'=%s
                         AND params->>'run_day'=%s ORDER BY id DESC LIMIT 1""", (str(brand_id), day))
        row = cur.fetchone()
        if row is None: return None
        if isinstance(row, dict): return row
        return {"id": row[0], "status": row[1], "created_at": row[2], "params": row[3]}


def insert_task(conn, brand_id: int, day: str, config_digest: str) -> int:
    params = json.dumps({"brand_id": brand_id, "run_day": day, "config_digest": config_digest})
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO tasks(type,status,params,triggered_by,progress,progress_text)
                      VALUES('owned_marketing_run','waiting_children',%s,'scheduled-owned-marketing',0,'Codex marketing run started') RETURNING id""", (params,))
        row = cur.fetchone()
        task_id = row["id"] if isinstance(row, dict) else row[0]
    conn.commit()
    return int(task_id)


def finish_task(conn, task_id: int, status: str, report: dict[str, Any]) -> None:
    if status not in SAFE_STATUS:
        raise ValueError("invalid task status")
    with conn.cursor() as cur:
        cur.execute("""UPDATE tasks SET status=%s,progress=%s,progress_text=%s,
                      result_ref=%s,error=%s,finished_at=CASE WHEN %s IN ('done','failed') THEN now() ELSE finished_at END
                      WHERE id=%s""", (status, 100 if status in ("done", "failed") else 0,
                      report.get("summary", "")[:500], json.dumps(report), report.get("error"), status, task_id))
    conn.commit()


def write_receipt(report: dict[str, Any], day: str, brand_id: int) -> Path:
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = STATE / f"receipt-{brand_id}-{day}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(report, sort_keys=True).encode())
    finally:
        os.close(fd)
    return path


def final_text(stream: str, secrets: list[str] | None = None) -> str:
    found: list[str] = []
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") in {"agent_message", "assistant_message"}:
            text = event.get("text") or event.get("message")
            if isinstance(text, str):
                found.append(text)
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            found.append(item["text"])
        for key in ("message", "result"):
            obj = event.get(key)
            if isinstance(obj, dict) and isinstance(obj.get("text"), str):
                found.append(obj["text"])
    return redact(found[-1] if found else "", secrets)[:6000]


def usage(stream: str) -> dict[str, int]:
    incoming = outgoing = 0
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidates = [event.get("usage")]
        for key in ("result", "turn"):
            if isinstance(event.get(key), dict):
                candidates.append(event[key].get("usage"))
        for item in candidates:
            if isinstance(item, dict):
                incoming += int(item.get("input_tokens", item.get("prompt_tokens", 0)) or 0)
                outgoing += int(item.get("output_tokens", item.get("completion_tokens", 0)) or 0)
                break
    return {"input_tokens": incoming, "output_tokens": outgoing}


def _process(command, **kwargs):
    timeout = kwargs.pop("timeout", None)
    if kwargs.pop("capture_output", False):
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    kwargs["stdin"] = subprocess.DEVNULL
    proc = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try: out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL); out, err = proc.communicate()
        raise subprocess.TimeoutExpired(command, timeout, output=out, stderr=err)
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def run_codex(prompt_file: Path, timeout: int, workdir: Path = ROOT, runner: Callable[..., subprocess.CompletedProcess] = _process) -> tuple[int, str]:
    prompt = prompt_file.read_text()
    command = ["codex", "exec", "--json", "-C", str(workdir), "--sandbox", "workspace-write", "--skip-git-repo-check", prompt]
    result = runner(command, capture_output=True, text=True, timeout=timeout, env=clean_env(), cwd=str(workdir))
    raw = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    return int(result.returncode), raw


def execute(brand_id: int, config_path: Path, dry_run: bool = False, *, now: datetime | None = None, db=connect, runner=None) -> dict[str, Any]:
    config = read_config(config_path)
    item = brand_config(config, brand_id)
    day = (now or datetime.now(timezone.utc)).date().isoformat()
    if dry_run:
        return {"ok": True, "dry_run": True, "brand_id": brand_id, "run_day": day, "timeout_seconds": item["timeout_seconds"]}
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = STATE / f"brand-{brand_id}.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": True, "skipped": "another run is active", "brand_id": brand_id, "run_day": day}
        env = load_env()
        conn = db(env)
        try:
            project_id = item.get("project_id")
            if not active_brand(conn, brand_id, int(project_id) if project_id is not None else None):
                return {"ok": False, "skipped": "brand project is not active"}
            prior = existing_today(conn, brand_id, day)
            if prior:
                return {"ok": True, "skipped": "already handled today", "task_id": prior["id"], "status": prior["status"]}
            digest_input = config_path.read_bytes() + b"\0" + item["prompt_file"].read_bytes()
            digest = __import__("hashlib").sha256(digest_input).hexdigest()
            task_id = insert_task(conn, brand_id, day, digest)
            log_path = STATE / f"brand-{brand_id}-{day}.jsonl"
            try:
                code, raw = run_codex(item["prompt_file"], item["timeout_seconds"], item["workdir"], runner=runner or _process)
                fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                secret_values = [value for name, value in env.items() if re.search(r"PASSWORD|PASSWD|SECRET|TOKEN|CREDENTIAL|API_KEY|ACCESS_KEY|PRIVATE_KEY", name, re.I)]
                try: os.write(fd, redact(raw, secret_values).encode())
                finally: os.close(fd)
                report = {"task_id": task_id, "brand_id": brand_id, "run_day": day, "summary": final_text(raw, secret_values), "usage": usage(raw), "log_ref": str(log_path), "exit_code": code}
                if code:
                    report.update({"ok": False, "error": "Codex exited nonzero"})
                    write_receipt(report, day, brand_id)
                    try: finish_task(conn, task_id, "failed", report)
                    except Exception as exc:
                        report.update({"ok": False, "error": f"task finalization failed: {type(exc).__name__}"})
                        write_receipt(report, day, brand_id)
                elif not report["summary"]:
                    report.update({"ok": False, "error": "Codex exited successfully without an assistant final"})
                    write_receipt(report, day, brand_id)
                    try: finish_task(conn, task_id, "failed", report)
                    except Exception as exc:
                        report.update({"ok": False, "error": f"task finalization failed: {type(exc).__name__}"})
                        write_receipt(report, day, brand_id)
                else:
                    report["ok"] = True
                    write_receipt(report, day, brand_id)
                    try: finish_task(conn, task_id, "done", report)
                    except Exception as exc:
                        report.update({"ok": False, "error": f"task finalization failed: {type(exc).__name__}"})
                        write_receipt(report, day, brand_id)
                return report
            except subprocess.TimeoutExpired:
                report = {"ok": False, "task_id": task_id, "brand_id": brand_id, "run_day": day, "error": "Codex timed out; no automatic retry today", "summary": ""}
                write_receipt(report, day, brand_id)
                try: finish_task(conn, task_id, "failed", report)
                except Exception as exc:
                    report.update({"ok": False, "error": f"task finalization failed: {type(exc).__name__}"})
                    write_receipt(report, day, brand_id)
                return report
            except Exception as exc:
                report = {"ok": False, "task_id": task_id, "brand_id": brand_id, "run_day": day, "error": f"runner error: {type(exc).__name__}", "summary": ""}
                write_receipt(report, day, brand_id)
                try: finish_task(conn, task_id, "failed", report)
                except Exception as exc:
                    report.update({"ok": False, "error": f"task finalization failed: {type(exc).__name__}"})
                    write_receipt(report, day, brand_id)
                return report
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand-id", type=int, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = execute(args.brand_id, args.config, args.dry_run)
        print(json.dumps(result))
        return 0 if result.get("ok") else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
