#!/usr/bin/env python3
"""Compact routine agent lifecycle traces after the 90-day raw window."""

from __future__ import annotations

import sys

import agent_trace


def main() -> int:
    try:
        result = agent_trace.compact_old_traces(retention_days=90)
    except Exception:
        alert = agent_trace._append({
            "trace_id": agent_trace.trace_id(),
            "session_id": "scheduled-agent-trace-compaction",
            "turn_id": "",
            "kind": "alert",
            "status": "needs_human",
            "severity": "urgent",
            "summary": "Agent trace compaction integrity check failed; source traces were preserved.",
            "refs": ["/home/agency/agency-os/scripts/compact_agent_traces.py"],
            "redacted": True,
        })
        try:
            agent_trace.notify_active_urgent([alert])
        except Exception:
            pass
        print("Agent trace compaction failed; source traces were preserved", file=sys.stderr)
        return 1
    if not result["files"]:
        print(f"NOOP no raw agent traces older than {result['cutoff']}")
        return 0
    agent_trace._append({
        "trace_id": agent_trace.trace_id(),
        "session_id": "scheduled-agent-trace-compaction",
        "turn_id": "",
        "kind": "result",
        "status": "verified",
        "severity": "info",
        "summary": (
            f"Compacted {result['files']} old trace file(s): "
            f"{result['source_records']} source records, "
            f"{result['compacted_records']} routine records summarized."
        ),
        "refs": ["/home/agency/.local/state/agency-os/agent-traces/archive/manifest.json"],
        "redacted": True,
    })
    print(
        f"Compacted {result['files']} agent trace file(s); "
        f"preserved {result['retained_records']} archive record(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
