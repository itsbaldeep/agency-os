#!/bin/bash
# Daily Docker build cache prune — logs reclaim via orch trace
set -e

LOG_FILE="/home/agency/agency-os/logs/prune.log"
DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Run prune and capture output
OUTPUT=$(docker buildx prune -af 2>&1) || true

# Parse reclaimed space (look for "Total: XXXX" or last line)
RECLAIMED=$(echo "$OUTPUT" | grep -i "total" | tail -1 | grep -oP '[0-9.]+\s*[kMGTP]?B' || echo "unknown")
SPACE_NOW=$(df -h / | tail -1 | awk '{print $5}')

echo "$DATE reclaimed=$RECLAIMED space=$SPACE_NOW" >> "$LOG_FILE"

# job_runs already proves the cron executed. Emit an event only when the prune
# actually reclaimed something; zero-result heartbeats add no operator value.
if [[ "$RECLAIMED" != "unknown" && ! "$RECLAIMED" =~ ^0+(\.0+)?[[:space:]]*[kMGTP]?B$ ]] && command -v orch &>/dev/null; then
    orch trace "$(cat <<JSON
{
    "project": "system",
    "actor": "cron",
    "action": "docker_prune",
    "detail": "Build cache prune reclaimed $RECLAIMED, disk now $SPACE_NOW",
    "gate": "green",
    "decision": "proceed",
    "ok": 1
}
JSON
)" 2>/dev/null || true
fi
