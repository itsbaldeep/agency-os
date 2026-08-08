#!/bin/bash
# run-job.sh — unified job runner for cron and manual triggers
# Usage: run-job.sh <job_id> [trigger_type]
#   trigger_type: "scheduled" (default) or "manual"
set -e

JOB_ID="${1:?Usage: run-job.sh <job_id> [trigger_type]}"
TRIGGER="${2:-scheduled}"
LOCKFILE="/tmp/agency-job-${JOB_ID}.lock"
PGHOST="100.64.0.1"
PGUSER="agency"
PGPW=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)
export PGPASSWORD="$PGPW"

# Reachability check
if ! psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c "SELECT 1" >/dev/null; then
  echo "$(date +%Y-%m-%dT%H:%M:%S) REACHABILITY CHECK FAILED: psql could not connect to agencyos on $PGHOST" >> /home/agency/agency-os/logs/errors.log
  exit 1
fi

# Flock — don't overlap
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Job $JOB_ID already running, skipping"; exit 0; }

# Look up job
JOB_INFO=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -F'|' -c \
  "SELECT id, name, script_path FROM background_jobs WHERE id=$JOB_ID AND enabled=true")
JOB_NAME=$(echo "$JOB_INFO" | cut -d'|' -f2)
SCRIPT_PATH=$(echo "$JOB_INFO" | cut -d'|' -f3)

[ -z "$JOB_NAME" ] && { echo "Job $JOB_ID not found or disabled"; exit 1; }

# Stale-run sweep — mark runs still 'running' past 30 min as failed
psql -h "$PGHOST" -U "$PGUSER" -d agencyos -c \
  "UPDATE job_runs SET status='failed', finished_at=now(), duration_sec=EXTRACT(EPOCH FROM now() - started_at)::int, detail='Stale run — no completion recorded (swept by run-job.sh)' WHERE job_id=$JOB_ID AND status='running' AND started_at < now() - interval '30 minutes'"

# Insert job_runs row
RUN_ID=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "INSERT INTO job_runs (job_id, triggered_by, status) VALUES ($JOB_ID, '$TRIGGER', 'running') RETURNING id" | head -1)

echo "Starting $JOB_NAME (run=$RUN_ID, trigger=$TRIGGER)"
START_TS=$(date +%s)

# Execute the script
SCRIPT_EXIT=0
SCRIPT_OUTPUT=""
if [ -x "$SCRIPT_PATH" ]; then
  SCRIPT_OUTPUT=$(timeout 300 bash "$SCRIPT_PATH" 2>&1) || SCRIPT_EXIT=$?
else
  SCRIPT_OUTPUT="Script not found or not executable: $SCRIPT_PATH"
  SCRIPT_EXIT=1
fi

DURATION=$(( $(date +%s) - START_TS ))
STATUS="completed"
[ "$SCRIPT_EXIT" -ne 0 ] && STATUS="failed"

# Truncate detail to 1000 chars
DETAIL="${SCRIPT_OUTPUT:0:1000}"

# Update job_runs
DETAIL_SAFE=$(echo "$DETAIL" | tr '\n' ' ' | sed "s/'/''/g")
psql -h "$PGHOST" -U "$PGUSER" -d agencyos -c \
  "UPDATE job_runs SET status='$STATUS', finished_at=now(), duration_sec=$DURATION, detail='$DETAIL_SAFE' WHERE id=$RUN_ID"

# Notify on failure (throttled, never fatal)
if [ "$STATUS" = "failed" ] && [ -n "$RUN_ID" ]; then
  MARKER="/home/agency/agency-os/logs/.alert-$JOB_NAME"
  if [ ! -e "$MARKER" ] || [ "$(( $(date +%s) - $(stat -c %Y "$MARKER") ))" -ge 1800 ]; then
    WEBHOOK=$(grep DISCORD_WEBHOOK_URL /home/agency/agency-os/.env | cut -d= -f2)
    if [ -n "$WEBHOOK" ]; then
      NOTIFY_DETAIL=$(echo "$DETAIL" | tr '\n' ' ' | tr '"' "'" | cut -c1-300)
      curl -sf --max-time 10 -H "Content-Type: application/json" \
        -d "{ \"content\": \"🚨 job $JOB_NAME failed (run $RUN_ID): $NOTIFY_DETAIL\" }" \
        "$WEBHOOK" && touch "$MARKER"
    fi
  fi
fi

echo "$JOB_NAME completed: $STATUS in ${DURATION}s"
flock -u 200
