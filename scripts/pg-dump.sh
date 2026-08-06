#!/bin/bash
# Nightly Postgres dump
export PGPASSWORD=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)
BACKUP_DIR="/home/agency/agency-os/backups"
mkdir -p "$BACKUP_DIR"

filename="agencyos_$(date +%Y%m%d_%H%M%S).sql.gz"
pg_dump -h 100.64.0.1 -U agency agencyos | gzip > "$BACKUP_DIR/$filename"

# Keep only last 7 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup done: $filename"
