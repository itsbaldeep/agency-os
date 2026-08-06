#!/bin/bash
# sync-system-state.sh — pull everything that lives OUTSIDE ~/agency-os into
# the repo, so `git log` becomes the changelog of the whole machine.
# Run after any system change; also worth a weekly background_jobs entry.
set -euo pipefail
REPO="/home/agency/agency-os"
cd "$REPO"

mkdir -p infra/systemd infra/cron infra/caddy infra/docker infra/opencode

# 1. Our systemd units (the custom ones only)
for u in agency-worker agency-bot opencode caddy-ask headscale; do
  [ -f "/etc/systemd/system/$u.service" ] && cp "/etc/systemd/system/$u.service" infra/systemd/
done
cp -r /etc/systemd/system/opencode.service.d infra/systemd/ 2>/dev/null || true

# 2. Crontab
crontab -l > infra/cron/agency.crontab 2>/dev/null || true

# 3. Caddy config
sudo cat /etc/caddy/Caddyfile > infra/caddy/Caddyfile 2>/dev/null || true

# 4. Sudoers fragment (reference copy)
sudo cat /etc/sudoers.d/agency-executor > infra/sudoers-agency-executor 2>/dev/null || true

# 5. Docker: compose files are in project repos; here we snapshot the manifest
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.HostConfig.RestartPolicy.Name}}' \
  > infra/docker/container-manifest.tsv 2>/dev/null || \
docker ps -a --format '{{.Names}}\t{{.Image}}' > infra/docker/container-manifest.tsv

# 6. OpenCode config (not credentials)
cp /home/agency/.opencode/opencode.jsonc infra/opencode/ 2>/dev/null || true

# 7. DB schema (structure only, no data — data belongs to backups)
PGPASSWORD=$(grep POSTGRES_PASSWORD "$REPO/.env" | cut -d= -f2) \
  pg_dump -h 100.64.0.1 -U agency -d agencyos --schema-only > infra/agencyos-schema.sql

# 8. Package inventory for the bootstrap script
dpkg --get-selections | grep -v deinstall > infra/apt-packages.txt

echo "synced. review with: git status && git diff"
