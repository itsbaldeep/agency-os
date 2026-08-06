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

# Flock — don't overlap
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Job $JOB_ID already running, skipping"; exit 0; }

# Look up job
JOB_INFO=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -F'|' -c \
  "SELECT id, name, script_path FROM background_jobs WHERE id=$JOB_ID AND enabled=true" 2>/dev/null)
JOB_NAME=$(echo "$JOB_INFO" | cut -d'|' -f2)
SCRIPT_PATH=$(echo "$JOB_INFO" | cut -d'|' -f3)

[ -z "$JOB_NAME" ] && { echo "Job $JOB_ID not found or disabled"; exit 1; }

# Stale-run sweep — mark runs still 'running' past 30 min as failed
psql -h "$PGHOST" -U "$PGUSER" -d agencyos -c \
  "UPDATE job_runs SET status='failed', finished_at=now(), duration_sec=EXTRACT(EPOCH FROM now() - started_at)::int, detail='Stale run — no completion recorded (swept by run-job.sh)' WHERE job_id=$JOB_ID AND status='running' AND started_at < now() - interval '30 minutes'" 2>/dev/null

# Insert job_runs row
RUN_ID=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "INSERT INTO job_runs (job_id, triggered_by, status) VALUES ($JOB_ID, '$TRIGGER', 'running') RETURNING id" 2>/dev/null | head -1)

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
  "UPDATE job_runs SET status='$STATUS', finished_at=now(), duration_sec=$DURATION, detail='$DETAIL_SAFE' WHERE id=$RUN_ID" 2>/dev/null

echo "$JOB_NAME completed: $STATUS in ${DURATION}s"
flock -u 200
