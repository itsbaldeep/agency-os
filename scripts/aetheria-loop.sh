#!/bin/bash
# aetheria-loop.sh — enqueue ONE aetheria_work_block task for the worker to run.
#
# Job 12 (hourly). Enqueue-only: exits in seconds so it fits run-job.sh's 300s
# cap. The real work block runs in worker.py:handle_aetheria_work_block as a
# headless `opencode run` session (≤40 min), per docs/AGENCY_INTEGRATION.md §1.
#
# Guards (skip + exit 0, logging why, when ANY trips):
#  - .manual present AND newer than 24h (human driving a manual session);
#  - an aetheria_work_block task is already queued/running;
#  - a pending aetheria_gate approval (human gate unanswered);
#  - today's aetheria spend ≥ AETHERIA_DAILY_BUDGET_USD (default 3.00);
#  - STATE.md "Next action" starts with "HUMAN:" (agent parked the loop).
# Belt-and-braces: a .manual older than 24h is ignored + traced (no permanent
# lockout — fixes the old deadlock that stranded job 12).
set -euo pipefail

REPO="$HOME/projects/aetheria"
PGHOST="100.64.0.1"
PGUSER="agency"
PGPW=$(grep POSTGRES_PASSWORD "$HOME/agency-os/.env" | cut -d= -f2)
export PGPASSWORD="$PGPW"
DAILY_BUDGET="${AETHERIA_DAILY_BUDGET_USD:-3.00}"
PROJ_ID=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "SELECT id FROM projects WHERE name='aetheria' OR repo_name='aetheria' LIMIT 1" 2>/dev/null || true)

trace() {
  # best-effort ClickHouse trace (never fatal)
  local action="$1" detail="$2"
  CH_AUTH=$(printf 'agency:%s' "$(grep CLICKHOUSE_PASSWORD "$HOME/agency-os/.env" | cut -d= -f2)" | base64)
  printf 'INSERT INTO default.events (project,actor,action,detail,gate,decision,ok) FORMAT TabSeparated\naetheria\tenqueuer\t%s\t%s\tgreen\tproceed\t1\n' \
    "$action" "$detail" \
  | curl -sf --max-time 5 -H "Authorization: Basic $CH_AUTH" -H "User-Agent: AetheriaLoop/1.0" \
        --data-binary @- "http://100.64.0.1:8123/" >/dev/null 2>&1 || true
}

skip() { echo "skip: $*"; trace "enqueue_skipped" "$*"; exit 0; }

# 1. .manual — but ignore if older than 24h (the old permanent-lockout bug).
if [ -f "$REPO/.manual" ]; then
  if [ -n "$(find "$REPO/.manual" -mmin +1440 2>/dev/null)" ]; then
    echo "warn: .manual older than 24h — ignoring + tracing (no permanent lockout)"
    trace "manual_marker_expired" ".manual stale >24h, ignored"
  else
    skip ".manual lock present (human working in repo)"
  fi
fi

# 2. Already a work block queued/running?
QUEUED=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "SELECT count(*) FROM tasks WHERE type='aetheria_work_block' AND status IN ('queued','running')" 2>/dev/null || echo 0)
[ "${QUEUED:-0}" -gt 0 ] && skip "an aetheria_work_block task is already queued/running"

# 3. Pending aetheria_gate approval (human gate unanswered — pauses the loop).
if [ -n "$PROJ_ID" ]; then
  GATES=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
    "SELECT count(*) FROM approvals WHERE project_id=$PROJ_ID AND type='aetheria_gate' AND status='pending'" 2>/dev/null || echo 0)
  [ "${GATES:-0}" -gt 0 ] && skip "pending aetheria_gate approval (human gate unanswered)"
fi

# 4. Daily budget exhausted (sum of today's aetheria task cost).
#    tasks has no project_id column; aetheria tasks carry params->>'repo'.
SPENT=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "SELECT COALESCE(round(sum(cost)::numeric,2),0) FROM tasks WHERE type='aetheria_work_block' AND cost IS NOT NULL AND finished_at >= date_trunc('day', now())" 2>/dev/null || echo 0)
if awk "BEGIN{exit !($SPENT >= $DAILY_BUDGET)}"; then
  skip "daily budget exhausted: spent=\$${SPENT} >= budget=\$${DAILY_BUDGET}"
fi

# 5. STATE.md "Next action" parked by the agent with HUMAN:.
NEXT=$(grep -m1 '^## Next action' -A2 "$REPO/docs/STATE.md" 2>/dev/null | grep -m1 'HUMAN:' || true)
[ -n "$NEXT" ] && skip "STATE.md Next action is HUMAN-parked: $NEXT"

# 6. Determine model from the Next action tag (escalation rule, §1.2/§6).
NEXT_LINE=$(grep -m1 '^## Next action' -A6 "$REPO/docs/STATE.md" 2>/dev/null | grep -E -m1 '\[UI\]|\[shader\]|\[arch\]' || true)
MODEL="${AETHERIA_MODEL:-opencode/deepseek-v4-flash}"
if [ -n "$NEXT_LINE" ]; then
  MODEL="opencode/glm-5.2"
fi

# 7. Enqueue (tasks has no project_id; aetheria is identified by params->>'repo'). Exit in seconds.
TASK_ID=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "INSERT INTO tasks (type, params, triggered_by) VALUES ('aetheria_work_block', jsonb_build_object('repo','aetheria','model','$MODEL'), 'scheduled') RETURNING id" 2>/dev/null | head -1)
[ -z "$TASK_ID" ] && { echo "ERROR: enqueue INSERT failed"; exit 1; }
trace "work_block_enqueued" "task=$TASK_ID model=$MODEL"
echo "enqueued task=$TASK_ID model=$MODEL"
