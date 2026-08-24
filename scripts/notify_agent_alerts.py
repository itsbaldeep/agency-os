#!/usr/bin/env python3
"""Deliver active urgent agent alerts to Discord with durable deduplication."""

from __future__ import annotations

import agent_trace


def main() -> int:
    result = agent_trace.notify_active_urgent()
    if result["active"] and not result["configured"]:
        print("Agent alert notification failed: Discord webhook is not configured")
        return 1
    if result["failed"]:
        print(f"Agent alert notification failed for {result['failed']} alert(s)")
        return 1
    if result["sent"]:
        print(f"Delivered {result['sent']} urgent agent alert(s); dashboard remains authoritative")
        return 0
    print(f"NOOP urgent agent alerts: {result['active']} active, {result['suppressed']} already delivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
