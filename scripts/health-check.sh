#!/bin/bash
# Health check — probe running containers, write results to Postgres
set -e

PGCONN="host=100.64.0.1 port=5432 dbname=agencyos user=agency"
export PGPASSWORD=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)

# Get all running services
services=$(docker ps --format '{{.Names}}' 2>/dev/null)

while IFS= read -r container; do
    # Skip control plane containers
    if [[ "$container" == "agency-postgres" || "$container" == "agency-clickhouse" ]]; then
        continue
    fi

    # Check if container is running
    status=$(docker inspect --format='{{.State.Running}}' "$container" 2>/dev/null || echo "false")

    if [ "$status" = "true" ]; then
        healthy=true
        detail="running"
    else
        healthy=false
        detail="not running"
    fi

    # Write to Postgres
    psql "$PGCONN" -c "
        INSERT INTO health_checks (service_id, healthy, detail)
        SELECT s.id, $healthy, '$detail'
        FROM services s
        WHERE s.container = '$container'
        LIMIT 1;
    " 2>/dev/null || true

done <<< "$services"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) health check done"
