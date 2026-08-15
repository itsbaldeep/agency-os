#!/bin/bash
# competitor-scan-enqueue.sh — enqueue competitor_scan tasks for all opt-in competitors.
# Runs weekly via cron. No LLM, no fetching — the worker does the scanning.
set -e
PGHOST="100.64.0.1"
PGUSER="agency"
PGPW=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)
export PGPASSWORD="$PGPW"

COUNT=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "INSERT INTO tasks (type, params, triggered_by)
   SELECT 'competitor_scan', jsonb_build_object('competitor_id', id), 'scheduled'
   FROM competitors WHERE scan_enabled=true RETURNING id" | grep -E '^[0-9]+$' | wc -l)

if [ "$COUNT" -eq 0 ]; then
  echo "0 competitors enabled — nothing enqueued"
else
  echo "$COUNT enqueued"
fi
