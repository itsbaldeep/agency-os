#!/bin/bash
# Health check — probe expected active containers; retain changes + hourly heartbeat
set -e

PGCONN="host=100.64.0.1 port=5432 dbname=agencyos user=agency"
export PGPASSWORD=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)

services=$(psql "$PGCONN" -t -A -F'|' -c "
  SELECT s.id,s.container
  FROM services s JOIN projects p ON p.id=s.project_id
  WHERE p.lifecycle='active' AND s.status='running' AND s.container IS NOT NULL
  ORDER BY s.id
" 2>/dev/null)

written=0
while IFS='|' read -r service_id container; do
    [ -z "$service_id" ] && continue
    if [ "$(docker inspect --format='{{.State.Running}}' "$container" 2>/dev/null || true)" = "true" ]; then
        healthy=true
        detail="running"
    else
        healthy=false
        detail="expected active container is absent"
    fi
    inserted=$(psql "$PGCONN" -q -t -A -c "
      INSERT INTO health_checks (service_id,healthy,detail)
      SELECT $service_id,$healthy,'$detail'
      WHERE NOT EXISTS (
        SELECT 1 FROM health_checks h
        WHERE h.service_id=$service_id AND h.healthy=$healthy
          AND h.ts > now()-interval '1 hour'
      ) RETURNING id
    " 2>/dev/null)
    [ -n "$inserted" ] && written=$((written + 1))
done <<< "$services"

if [ "$written" -eq 0 ]; then
    echo "NOOP health state unchanged"
else
    echo "health state recorded for $written service(s)"
fi
