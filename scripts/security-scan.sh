#!/bin/bash
# Security & Bug Fix Scanner — runs every 12 hours
# Scans all projects, logs results, traces to ClickHouse.
# Does NOT create approvals for routine output.
# Only raises an alert (type=other) if genuinely NEW high-severity findings appear.

ROOTS=("/home/agency/core" "/home/agency/engagements")
LOG="/home/agency/agency-os/logs/scanner.log"
DEDUP_FILE="/home/agency/agency-os/data/scanner-findings-hash.txt"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "$TS === Scanner started ===" | tee -a "$LOG"

TOTAL_BUGS=0
TOTAL_FIXED=0
PROJECTS_SCANNED=0
SCAN_START=$(date +%s)

ALL_FINDINGS=""

for root in "${ROOTS[@]}"; do
for project_dir in "$root"/*/; do
    proj=$(basename "$project_dir")
    [ -f "${project_dir}package.json" ] || [ -f "${project_dir}requirements.txt" ] || continue

    echo "$TS Scanning $proj..." | tee -a "$LOG"

    cd "$project_dir"

    # --- npm audit (Node projects) ---
    if [ -f package.json ]; then
        if [ -d node_modules ]; then
            AUDIT=$(timeout 30 npm audit --json 2>/dev/null || true)
            VULN_COUNT=$(echo "$AUDIT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    vulns = d.get('vulnerabilities', {})
    # Only count high/critical
    high = sum(1 for v in vulns.values() if v.get('severity') in ('high', 'critical'))
    print(high)
except:
    print(0)
" 2>/dev/null || echo 0)
            if [ "$VULN_COUNT" -gt 0 ]; then
                echo "$TS   $VULN_COUNT high/critical npm vulns in $proj" | tee -a "$LOG"
                ALL_FINDINGS+="$proj:npm:$VULN_COUNT"$'\n'
                TOTAL_BUGS=$((TOTAL_BUGS + VULN_COUNT))
                # Report only. Dependency mutation belongs in a reviewed core or
                # engagement change, never in a scheduled scanner.
            else
                echo "$TS   npm audit: no high/critical vulns in $proj" | tee -a "$LOG"
            fi
        fi
    fi

    # --- gitleaks (all projects) ---
    GITLEAKS_OUT=$(timeout 60 /home/agency/.local/bin/gitleaks detect \
        --source "$project_dir" --no-git \
        --config /home/agency/agency-os/.gitleaks.toml \
        -f json 2>/dev/null || true)
    FINDING_COUNT=$(echo "$GITLEAKS_OUT" | python3 -c "
import sys, json
count = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        json.loads(line)
        count += 1
    except:
        pass
print(count)
" 2>/dev/null || echo 0)
    if [ "$FINDING_COUNT" -gt 0 ]; then
        echo "$TS   $FINDING_COUNT gitleaks findings in $proj" | tee -a "$LOG"
        ALL_FINDINGS+="$proj:gitleaks:$FINDING_COUNT"$'\n'
        TOTAL_BUGS=$((TOTAL_BUGS + FINDING_COUNT))
    else
        echo "$TS   gitleaks: no leaks found in $proj" | tee -a "$LOG"
    fi

    # --- Python dependency check ---
    if [ -f requirements.txt ]; then
        PY_ISSUES=$(timeout 30 pip-audit --quiet 2>/dev/null | wc -l || echo 0)
        if [ "$PY_ISSUES" -gt 0 ]; then
            echo "$TS   $PY_ISSUES Python dependency issues in $proj" | tee -a "$LOG"
            ALL_FINDINGS+="$proj:pip:$PY_ISSUES"$'\n'
            TOTAL_BUGS=$((TOTAL_BUGS + PY_ISSUES))
        else
            echo "$TS   pip-audit: no issues in $proj" | tee -a "$LOG"
        fi
    fi

    # --- Dockerfile root check ---
    if [ -f Dockerfile ]; then
        if grep -q '^USER' Dockerfile 2>/dev/null; then
            echo "$TS   Dockerfile: has USER directive (good)" | tee -a "$LOG"
        else
            echo "$TS   Dockerfile: runs as root in $proj (cosmetic)" | tee -a "$LOG"
            ALL_FINDINGS+="$proj:dockerfile:root"$'\n'
            TOTAL_BUGS=$((TOTAL_BUGS + 1))
        fi
    fi

    # --- Tests: SKIPPED in cron (requires running stack) ---
    echo "$TS   tests: skipped (requires running Docker stack)" | tee -a "$LOG"

    PROJECTS_SCANNED=$((PROJECTS_SCANNED + 1))
done
done

SCAN_DURATION=$(( $(date +%s) - SCAN_START ))
echo "$TS === Scan complete: $PROJECTS_SCANNED repos, $TOTAL_BUGS issues, report-only, took ${SCAN_DURATION}s ===" | tee -a "$LOG"

# --- Dedup check: only alert if findings hash differs from last run ---
FINDINGS_HASH=$(echo -n "$ALL_FINDINGS" | md5sum | cut -d' ' -f1)
PREV_HASH=$(cat "$DEDUP_FILE" 2>/dev/null || echo "")

if [ "$TOTAL_BUGS" -gt 0 ] && [ "$FINDINGS_HASH" != "$PREV_HASH" ]; then
    echo "$TS   NEW findings detected (hash: $FINDINGS_HASH) — logging alert" | tee -a "$LOG"
    echo "$FINDINGS_HASH" > "$DEDUP_FILE"
    WEBHOOK=$(sed -n 's/^DISCORD_WEBHOOK_URL=//p' /home/agency/agency-os/.env | head -1)
    if [ -n "$WEBHOOK" ]; then
        curl -sf --max-time 10 -H 'Content-Type: application/json' \
          -d "{\"content\":\"🔐 Security scan: $TOTAL_BUGS new high-signal finding(s) across $PROJECTS_SCANNED repos. Review the dashboard/operations log; no automatic fix was applied.\"}" \
          "$WEBHOOK" >/dev/null || true
    fi
fi

# --- Log to ClickHouse via orch trace ---
if command -v orch &>/dev/null; then
    orch trace "$(cat <<JSON
{
    "project": "system",
    "actor": "cron",
    "action": "security_scan",
    "detail": "Scanned $PROJECTS_SCANNED repos, $TOTAL_BUGS issues, report-only, ${SCAN_DURATION}s, hash=$FINDINGS_HASH",
    "gate": "green",
    "decision": "proceed",
    "ok": 1
}
JSON
)" 2>/dev/null || true
fi

echo "$TS === Scanner finished ===" | tee -a "$LOG"
