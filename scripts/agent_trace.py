#!/usr/bin/env python3
"""Small, secret-free lifecycle trace index for Codex and OpenCode work.

The JSONL files are a navigation aid, not a source of truth. Prompt and model
outputs are represented only by hashes and byte counts. Human-written summaries
must stay bounded and secret-free; volatile claims need a freshness boundary.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
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
SCHEMA_VERSION = 1
MAX_SUMMARY = 600
MAX_REF = 500
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
    print(payload["trace_id"])
    return 0


def _iter_recent(days: int):
    cutoff = utc_now().date() - timedelta(days=max(0, days - 1))
    try:
        paths = sorted(TRACE_DIR.glob("????-??-??.jsonl"), reverse=True)
    except OSError:
        return
    for path in paths:
        try:
            if datetime.fromisoformat(path.stem).date() < cutoff:
                continue
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        yield value
                except (ValueError, TypeError):
                    continue
        except OSError:
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


def active_alerts(days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
    """Return unresolved human-attention records, newest first.

    A later terminal result or decision for the same trace resolves its alert.
    Other lifecycle noise must not accidentally clear a human request.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for item in reversed(list(_iter_recent(days))):
        tid = str(item.get("trace_id") or "")
        if not tid:
            continue
        state = grouped.setdefault(tid, {"active": False})
        kind = item.get("kind")
        status = str(item.get("status") or "")
        if kind == "alert" and status not in ("resolved", "done", "complete"):
            state.update(item)
            state["active"] = True
        elif kind in ("result", "decision", "alert") and status in (
            "resolved", "done", "complete", "verified"
        ):
            state["active"] = False
    values = [item for item in grouped.values() if item.get("active")]
    values.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    return values[: max(1, min(limit, 100))]


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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
