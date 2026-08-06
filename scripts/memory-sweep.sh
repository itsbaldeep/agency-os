#!/bin/bash
# Memory sweep — if free RAM below threshold, pause LRU preview container
THRESHOLD_MB=3000

free_mb=$(free -m | awk 'NR==2{print $7}')

if [ "$free_mb" -lt "$THRESHOLD_MB" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) low RAM: ${free_mb}MB free, sweeping LRU preview..."

    export PGPASSWORD=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)
    PGCONN="host=100.64.0.1 port=5432 dbname=agencyos user=agency"

    # Get LRU preview container (not live, last seen oldest)
    lru=$(psql "$PGCONN" -t -A -c "
        SELECT s.container FROM services s
        JOIN projects p ON p.id = s.project_id
        WHERE s.status='running'
        AND p.state='preview'
        AND s.container IS NOT NULL
        ORDER BY s.last_seen ASC NULLS FIRST
        LIMIT 1;
    " 2>/dev/null)

    if [ -n "$lru" ]; then
        docker stop "$lru"
        psql "$PGCONN" -c "
            UPDATE services SET status='stopped' WHERE container='$lru';
        " 2>/dev/null
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) paused: $lru"
    else
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) no preview containers to pause"
    fi
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) RAM ok: ${free_mb}MB free"
fi
