#!/usr/bin/env python3
"""Small, secret-free lifecycle trace index for Codex and OpenCode work.

The JSONL files are a navigation aid, not a source of truth. Prompt and model
outputs are represented only by hashes and byte counts. Human-written summaries
must stay bounded and secret-free; volatile claims need a freshness boundary.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TRACE_DIR = Path(
    os.environ.get(
        "AGENCY_AGENT_TRACE_DIR",
        "/home/agency/.local/state/agency-os/agent-traces",
    )
)
CURRENT_DIR = TRACE_DIR / "current"
ARCHIVE_DIR = TRACE_DIR / "archive"
ATTENTION_PATH = TRACE_DIR / "attention.json"
DISCORD_RECEIPTS_PATH = TRACE_DIR / "discord-receipts.json"
SCHEMA_VERSION = 1
MAX_SUMMARY = 600
MAX_REF = 500
MAX_DISCORD_RECEIPTS = 1000
MAX_URGENT_PER_RUN = 25
MAX_TRACE_FILE_BYTES = 64 * 1024 * 1024
TERMINAL_STATUSES = ("resolved", "done", "complete", "verified")
HIGH_VALUE_KINDS = ("research", "decision", "result", "alert")
SENSITIVE_VALUE = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization)"
    r"\s*[:=]\s*(?:bearer\s+)?\S+|-----BEGIN [A-Z ]+PRIVATE KEY-----"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def trace_id() -> str:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"atr_{stamp}_{secrets.token_hex(6)}"


def _safe_text(value: Any, limit: int, label: str) -> str:
    text = " ".join(str(value or "").split())[:limit]
    if SENSITIVE_VALUE.search(text):
        raise ValueError(f"{label} looks credential-bearing; record a redacted summary instead")
    return text


def _ensure_dirs() -> None:
    TRACE_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
    CURRENT_DIR.mkdir(mode=0o750, exist_ok=True)
    ARCHIVE_DIR.mkdir(mode=0o750, exist_ok=True)


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o640)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _read_attention() -> dict[str, Any] | None:
    try:
        payload = json.loads(ATTENTION_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("alerts"), dict):
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return None


def _attention_payload() -> dict[str, Any]:
    return _read_attention() or {"v": SCHEMA_VERSION, "updated_at": None, "alerts": {}}


def _update_attention_locked(record: dict[str, Any]) -> None:
    tid = str(record.get("trace_id") or "")
    if not tid:
        return
    kind = str(record.get("kind") or "")
    status = str(record.get("status") or "")
    payload = _read_attention()
    rebuilt = payload is None
    if payload is None and "_build_attention_payload" in globals():
        payload = _build_attention_payload()
    payload = payload or {"v": SCHEMA_VERSION, "updated_at": None, "alerts": {}}
    alerts = payload["alerts"]
    changed = rebuilt
    if kind == "alert" and status not in TERMINAL_STATUSES:
        alerts[tid] = {
            key: record.get(key)
            for key in ("ts", "trace_id", "status", "severity", "summary", "refs")
            if record.get(key) not in (None, "", [])
        }
        changed = True
    elif kind in ("result", "decision", "alert") and status in TERMINAL_STATUSES:
        changed = alerts.pop(tid, None) is not None
    if changed:
        payload["updated_at"] = record.get("ts") or iso_now()
        _atomic_json(ATTENTION_PATH, payload)


def _append(record: dict[str, Any]) -> dict[str, Any]:
    _ensure_dirs()
    record = {"v": SCHEMA_VERSION, "ts": iso_now(), **record}
    day = record["ts"][:10]
    path = TRACE_DIR / f"{day}.jsonl"
    lock_path = TRACE_DIR / ".append.lock"
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, encoded.encode("utf-8"))
        finally:
            os.close(fd)
        _update_attention_locked(record)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return record


def _current_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")[:120]
    return CURRENT_DIR / f"{safe}.json"


def _write_current(session_id: str, payload: dict[str, Any]) -> None:
    _ensure_dirs()
    path = _current_path(session_id)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def _read_current(session_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(_current_path(session_id).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _base_from_hook(payload: dict[str, Any]) -> dict[str, Any]:
    current = _read_current(str(payload.get("session_id") or "unknown"))
    return {
        "trace_id": current.get("trace_id") or trace_id(),
        "session_id": str(payload.get("session_id") or "unknown")[:160],
        "turn_id": str(payload.get("turn_id") or current.get("turn_id") or "")[:160],
        "cwd": str(payload.get("cwd") or "")[:500],
        "model": str(payload.get("model") or "")[:100],
    }


def handle_hook() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
        event = str(payload.get("hook_event_name") or "unknown")
        base = _base_from_hook(payload)

        if event == "UserPromptSubmit":
            prompt = str(payload.get("prompt") or "")
            base["trace_id"] = trace_id()
            current = {
                "trace_id": base["trace_id"],
                "turn_id": base["turn_id"],
                "started_at": iso_now(),
            }
            _write_current(base["session_id"], current)
            _append({
                **base,
                "kind": "prompt",
                "status": "received",
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "prompt_chars": len(prompt),
                "redacted": True,
            })
            context = (
                f"Agency trace {base['trace_id']}. Before substantive work, route at least one "
                "bounded task to a Luna subagent. Search only a few relevant prior trace summaries; "
                "treat them as stale hints. Record material decisions, evidence, and completion with "
                "agent_trace.py record. Never put prompts, model output, or secrets in traces."
            )
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }))
            return 0

        record: dict[str, Any] = {**base, "kind": event, "status": "observed"}
        if event in ("SubagentStart", "SubagentStop"):
            record.update({
                "agent_id": str(payload.get("agent_id") or "")[:160],
                "agent_type": str(payload.get("agent_type") or "")[:120],
            })
            record["status"] = "started" if event == "SubagentStart" else "stopped"
        elif event == "PostToolUse":
            response = payload.get("tool_response")
            record.update({
                "tool_name": str(payload.get("tool_name") or "")[:160],
                "tool_use_id": str(payload.get("tool_use_id") or "")[:160],
                "response_sha256": hashlib.sha256(
                    json.dumps(response, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest(),
                "redacted": True,
            })
        elif event in ("PreCompact", "PostCompact"):
            record["trigger"] = str(payload.get("trigger") or "")[:40]
        elif event == "Stop":
            message = str(payload.get("last_assistant_message") or "")
            record.update({
                "status": "turn_stopped",
                "answer_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "answer_chars": len(message),
                "redacted": True,
            })
        _append(record)
        print("{}")
        return 0
    except Exception as exc:
        print(json.dumps({"systemMessage": f"Agency trace hook failed: {exc}"}))
        return 0


def _fresh_until(value: str | None) -> str | None:
    if not value:
        return None
    if value.isdigit():
        return (utc_now() + timedelta(days=int(value))).date().isoformat()
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def record(args: argparse.Namespace) -> int:
    current = _read_current(args.session_id) if args.session_id else {}
    tid = args.trace_id or current.get("trace_id") or trace_id()
    refs = [_safe_text(ref, MAX_REF, "reference") for ref in args.ref]
    payload = _append({
        "trace_id": tid,
        "session_id": args.session_id or "manual",
        "turn_id": current.get("turn_id") or "",
        "kind": args.kind,
        "status": args.status,
        "severity": args.severity,
        "summary": _safe_text(args.summary, MAX_SUMMARY, "summary"),
        "refs": refs,
        "fresh_until": _fresh_until(args.fresh_until),
        "redacted": True,
    })
    if (
        payload.get("kind") == "alert"
        and payload.get("severity") == "urgent"
        and payload.get("status") not in TERMINAL_STATUSES
    ):
        try:
            notify_active_urgent([payload])
        except Exception:
            # The durable alert remains authoritative and the scheduled notifier retries.
            pass
    print(payload["trace_id"])
    return 0


def _raw_lines_reverse(path: Path, max_bytes: int = MAX_TRACE_FILE_BYTES):
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        floor = max(0, position - max_bytes)
        remainder = b""
        while position > floor:
            block_size = min(64 * 1024, position - floor)
            position -= block_size
            handle.seek(position)
            chunks = (handle.read(block_size) + remainder).split(b"\n")
            remainder = chunks[0]
            for line in reversed(chunks[1:]):
                if line:
                    yield line.decode("utf-8", errors="replace")
        if remainder and floor == 0:
            yield remainder.decode("utf-8", errors="replace")


def _iter_recent(days: int):
    cutoff = utc_now().date() - timedelta(days=max(0, days - 1))
    try:
        by_day = {
            path.name.split(".jsonl", 1)[0]: path
            for path in ARCHIVE_DIR.glob("????/??/????-??-??.jsonl.gz")
        }
        by_day.update({path.stem: path for path in TRACE_DIR.glob("????-??-??.jsonl")})
    except OSError:
        return
    for day, path in sorted(by_day.items(), reverse=True):
        try:
            if datetime.fromisoformat(day).date() < cutoff:
                continue
            if path.suffix == ".gz":
                with gzip.open(path, "rb") as handle:
                    decoded = handle.read(MAX_TRACE_FILE_BYTES + 1)
                if len(decoded) > MAX_TRACE_FILE_BYTES:
                    continue
                lines = (line.decode("utf-8", errors="replace") for line in reversed(decoded.splitlines()))
            else:
                lines = _raw_lines_reverse(path)
            for line in lines:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        yield value
                except (ValueError, TypeError):
                    continue
        except (OSError, UnicodeError):
            continue


def _iter_all_chronological():
    try:
        by_day = {
            path.name.split(".jsonl", 1)[0]: path
            for path in ARCHIVE_DIR.glob("????/??/????-??-??.jsonl.gz")
        }
        by_day.update({path.stem: path for path in TRACE_DIR.glob("????-??-??.jsonl")})
    except OSError:
        return
    for _, path in sorted(by_day.items()):
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            yield value
                    except (ValueError, TypeError):
                        continue
        except (OSError, UnicodeError):
            continue


def search(args: argparse.Namespace) -> int:
    terms = [term.casefold() for term in args.terms]
    shown = 0
    for item in _iter_recent(args.days):
        haystack = " ".join([
            str(item.get("summary") or ""),
            " ".join(str(ref) for ref in item.get("refs") or []),
            str(item.get("kind") or ""),
        ]).casefold()
        if terms and not all(term in haystack for term in terms):
            continue
        if not item.get("summary") and item.get("kind") not in ("alert", "decision"):
            continue
        result = {
            key: item.get(key)
            for key in ("ts", "trace_id", "kind", "status", "severity", "summary", "refs", "fresh_until")
            if item.get(key) not in (None, "", [])
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        shown += 1
        if shown >= args.limit:
            break
    return 0


def _build_attention_payload() -> dict[str, Any]:
    alerts: dict[str, dict[str, Any]] = {}
    for item in _iter_all_chronological():
        tid = str(item.get("trace_id") or "")
        if not tid:
            continue
        kind = str(item.get("kind") or "")
        status = str(item.get("status") or "")
        if kind == "alert" and status not in TERMINAL_STATUSES:
            alerts[tid] = {
                key: item.get(key)
                for key in ("ts", "trace_id", "status", "severity", "summary", "refs")
                if item.get(key) not in (None, "", [])
            }
        elif kind in ("result", "decision", "alert") and status in TERMINAL_STATUSES:
            alerts.pop(tid, None)
    return {"v": SCHEMA_VERSION, "updated_at": iso_now(), "alerts": alerts}


def rebuild_attention() -> dict[str, Any]:
    """Rebuild the durable unresolved-alert index from all available traces."""
    _ensure_dirs()
    lock_path = TRACE_DIR / ".append.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        payload = _build_attention_payload()
        _atomic_json(ATTENTION_PATH, payload)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return payload


def active_alerts(days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
    """Return unresolved human-attention records, newest first.

    A later terminal result or decision for the same trace resolves its alert.
    Other lifecycle noise must not accidentally clear a human request.
    """
    del days  # Kept for CLI compatibility; unresolved alerts do not expire by age.
    payload = _read_attention() or rebuild_attention()
    values = list(payload.get("alerts", {}).values())
    values.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    return values[: max(1, min(limit, 100))]


def _core_env() -> dict[str, str]:
    from ops import core_env

    return core_env()


def _discord_payload(item: dict[str, Any]) -> dict[str, Any]:
    try:
        summary = _safe_text(item.get("summary"), MAX_SUMMARY, "alert summary")
    except ValueError:
        summary = "Urgent agent alert was redacted; review the dashboard."
    tid = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(item.get("trace_id") or "unknown"))[:100]
    timestamp = re.sub(r"[^0-9TZ:+.-]", "", str(item.get("ts") or ""))[:40]
    return {
        "content": (
            f"URGENT — Agency agent decision needed\n{summary}\n"
            f"Trace: `{tid}` · {timestamp}\nReview: http://100.64.0.1:5001/alerts"
        ),
        "allowed_mentions": {"parse": []},
    }


def _receipt_fingerprint(item: dict[str, Any]) -> str:
    selected = {
        key: item.get(key)
        for key in ("trace_id", "ts", "status", "severity", "summary")
    }
    encoded = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def notify_active_urgent(items: list[dict[str, Any]] | None = None) -> dict[str, int]:
    """Send new urgent alerts to Discord; the dashboard remains authoritative."""
    webhook = str(_core_env().get("DISCORD_WEBHOOK_URL") or "").strip()
    urgent = [
        item for item in (items if items is not None else active_alerts(limit=MAX_URGENT_PER_RUN))
        if item.get("severity") == "urgent"
    ][:MAX_URGENT_PER_RUN]
    if not webhook or not urgent:
        return {
            "active": len(urgent), "sent": 0, "suppressed": len(urgent), "failed": 0,
            "configured": int(bool(webhook)),
        }

    _ensure_dirs()
    lock_path = TRACE_DIR / ".discord.lock"
    sent = suppressed = failed = 0
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            receipts = json.loads(DISCORD_RECEIPTS_PATH.read_text(encoding="utf-8"))
            if not isinstance(receipts, dict):
                receipts = {}
        except (OSError, ValueError, TypeError):
            receipts = {}
        for item in urgent:
            fingerprint = _receipt_fingerprint(item)
            if fingerprint in receipts:
                suppressed += 1
                continue
            request = urllib.request.Request(
                webhook,
                data=json.dumps(_discord_payload(item)).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "agency-agent-alert/1"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    status = int(getattr(response, "status", response.getcode()))
                    if not 200 <= status < 300:
                        raise OSError(f"webhook returned HTTP {status}")
                receipts[fingerprint] = iso_now()
                newest = sorted(receipts.items(), key=lambda pair: pair[1], reverse=True)
                receipts = dict(newest[:MAX_DISCORD_RECEIPTS])
                _atomic_json(DISCORD_RECEIPTS_PATH, receipts)
                sent += 1
            except Exception:
                failed += 1
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return {
        "active": len(urgent), "sent": sent, "suppressed": suppressed, "failed": failed,
        "configured": 1,
    }


def _gzip_bytes(payload: bytes) -> bytes:
    with tempfile.SpooledTemporaryFile() as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as handle:
            handle.write(payload)
        output.seek(0)
        return output.read()


def _compacted_rows(rows: list[dict[str, Any]], source_sha256: str) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    routine: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("kind") in HIGH_VALUE_KINDS or row.get("severity") not in (None, "", "info"):
            retained.append(row)
        else:
            routine.setdefault(str(row.get("trace_id") or "unknown"), []).append(row)
    for tid, trace_rows in routine.items():
        timestamps = sorted(str(row.get("ts") or "") for row in trace_rows)
        canonical = "\n".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) for row in trace_rows
        ).encode("utf-8")
        retained.append({
            "v": SCHEMA_VERSION,
            "ts": timestamps[-1] if timestamps else "",
            "trace_id": tid,
            "kind": "trace_compaction",
            "status": "compacted",
            "severity": "info",
            "first_ts": timestamps[0] if timestamps else "",
            "last_ts": timestamps[-1] if timestamps else "",
            "record_count": len(trace_rows),
            "event_counts": dict(sorted(Counter(str(row.get("kind") or "unknown") for row in trace_rows).items())),
            "routine_sha256": hashlib.sha256(canonical).hexdigest(),
            "source_sha256": source_sha256,
            "redacted": True,
        })
    return sorted(retained, key=lambda row: (str(row.get("ts") or ""), str(row.get("trace_id") or "")))


def compact_old_traces(retention_days: int = 90, dry_run: bool = False) -> dict[str, Any]:
    """Compact lifecycle noise older than the exact-raw retention window."""
    cutoff = utc_now().date() - timedelta(days=max(1, retention_days))
    paths = []
    for path in sorted(TRACE_DIR.glob("????-??-??.jsonl")):
        try:
            path_date = datetime.fromisoformat(path.stem).date()
        except ValueError:
            continue
        if path_date < cutoff:
            if path.stat().st_size > MAX_TRACE_FILE_BYTES:
                raise ValueError(f"trace file exceeds safe compaction size: {path.name}")
            paths.append(path)
    report: dict[str, Any] = {
        "cutoff": cutoff.isoformat(),
        "files": 0,
        "source_records": 0,
        "retained_records": 0,
        "compacted_records": 0,
        "archives": [],
    }
    if dry_run:
        report["files"] = len(paths)
        report["dry_run"] = True
        return report

    _ensure_dirs()
    lock_path = TRACE_DIR / ".compaction.lock"
    append_lock_path = TRACE_DIR / ".append.lock"
    with lock_path.open("a", encoding="utf-8") as lock, \
         append_lock_path.open("a", encoding="utf-8") as append_lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        fcntl.flock(append_lock.fileno(), fcntl.LOCK_EX)
        manifest_path = ARCHIVE_DIR / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or not isinstance(manifest.get("archives"), dict):
                manifest = {"v": SCHEMA_VERSION, "archives": {}}
        except (OSError, ValueError, TypeError):
            manifest = {"v": SCHEMA_VERSION, "archives": {}}

        for path in paths:
            raw = path.read_bytes()
            source_sha = hashlib.sha256(raw).hexdigest()
            rows: list[dict[str, Any]] = []
            for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
                try:
                    row = json.loads(line)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"malformed trace record in {path.name}:{line_number}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"non-object trace record in {path.name}:{line_number}")
                rows.append(row)
            archive_rows = _compacted_rows(rows, source_sha)
            archive_payload = (
                "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in archive_rows)
            ).encode("utf-8")
            compressed = _gzip_bytes(archive_payload)
            target = ARCHIVE_DIR / path.stem[:4] / path.stem[5:7] / f"{path.stem}.jsonl.gz"
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            archive_sha = hashlib.sha256(compressed).hexdigest()
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != archive_sha:
                    raise ValueError(f"archive collision for {path.name}; source preserved")
            else:
                fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(compressed)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.chmod(temp_name, 0o640)
                    with gzip.open(temp_name, "rb") as handle:
                        if handle.read() != archive_payload:
                            raise ValueError(f"archive verification failed for {path.name}")
                    os.replace(temp_name, target)
                finally:
                    try:
                        os.unlink(temp_name)
                    except FileNotFoundError:
                        pass
            compacted_count = len(rows) - sum(
                1 for row in rows
                if row.get("kind") in HIGH_VALUE_KINDS or row.get("severity") not in (None, "", "info")
            )
            manifest["archives"][path.stem] = {
                "source_sha256": source_sha,
                "archive_sha256": archive_sha,
                "source_records": len(rows),
                "archive_records": len(archive_rows),
                "compacted_records": compacted_count,
                "path": str(target.relative_to(TRACE_DIR)),
            }
            manifest["updated_at"] = iso_now()
            _atomic_json(manifest_path, manifest)
            path.unlink()
            report["files"] += 1
            report["source_records"] += len(rows)
            report["retained_records"] += len(archive_rows)
            report["compacted_records"] += compacted_count
            report["archives"].append(str(target.relative_to(TRACE_DIR)))
        fcntl.flock(append_lock.fileno(), fcntl.LOCK_UN)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return report


def alerts(args: argparse.Namespace) -> int:
    for item in active_alerts(args.days, args.limit):
        result = {
            key: item.get(key)
            for key in ("ts", "trace_id", "status", "severity", "summary", "refs")
            if item.get(key) not in (None, "", [])
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("hook", help="consume one Codex hook payload from stdin")

    rec = sub.add_parser("record", help="append a bounded checkpoint, decision, result, or alert")
    rec.add_argument("--kind", choices=("checkpoint", "decision", "result", "research", "alert"), required=True)
    rec.add_argument("--status", default="recorded")
    rec.add_argument("--severity", choices=("info", "warning", "urgent"), default="info")
    rec.add_argument("--summary", required=True)
    rec.add_argument("--ref", action="append", default=[])
    rec.add_argument("--fresh-until", help="ISO date/time or number of days")
    rec.add_argument("--trace-id")
    rec.add_argument("--session-id", default="")

    query = sub.add_parser("search", help="search only bounded summaries and references")
    query.add_argument("terms", nargs="*")
    query.add_argument("--days", type=int, default=90)
    query.add_argument("--limit", type=int, default=5)

    alert_query = sub.add_parser("alerts", help="list unresolved human-attention summaries")
    alert_query.add_argument("--days", type=int, default=30)
    alert_query.add_argument("--limit", type=int, default=20)
    sub.add_parser("rebuild-attention", help="rebuild the durable unresolved-alert index")
    compact = sub.add_parser("compact", help="compact routine trace noise beyond retention")
    compact.add_argument("--retention-days", type=int, default=90)
    compact.add_argument("--dry-run", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "hook":
        return handle_hook()
    if args.command == "record":
        return record(args)
    if args.command == "search":
        return search(args)
    if args.command == "alerts":
        return alerts(args)
    if args.command == "rebuild-attention":
        payload = rebuild_attention()
        print(len(payload["alerts"]))
        return 0
    if args.command == "compact":
        print(json.dumps(compact_old_traces(args.retention_days, args.dry_run), sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
