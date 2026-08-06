#!/bin/bash
# bootstrap.sh — rebuild the Agency OS box on a fresh Ubuntu 24/26 server.
# Prereqs you bring by hand (the only two things not in git):
#   1. this repo cloned to /home/agency/agency-os  (git clone via a deploy token)
#   2. secrets restored to ~/agency-os/.env and ~/agency-os/bot/.env
#      (from your password manager — see .env.example for required keys)
# Data restore (pg dumps, minio) is a separate step at the bottom.
set -euo pipefail
REPO="/home/agency/agency-os"
cd "$REPO"

echo "== 1. base packages =="
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 python3-venv python3-pip \
  git curl jq postgresql-client caddy sqlite3
sudo usermod -aG docker agency

echo "== 2. tailscale + headscale (adjust to taste) =="
curl -fsSL https://tailscale.com/install.sh | sh
# headscale: install per current release docs, restore its config/db from backup

echo "== 3. opencode =="
curl -fsSL https://opencode.ai/install | bash
# then: opencode auth login   (interactive, needs your Zen key)

echo "== 4. python venv for the bot =="
python3 -m venv "$REPO/bot/.venv"
"$REPO/bot/.venv/bin/pip" install discord.py psycopg2-binary

echo "== 5. systemd units =="
sudo cp infra/systemd/*.service /etc/systemd/system/
[ -d infra/systemd/opencode.service.d ] && sudo cp -r infra/systemd/opencode.service.d /etc/systemd/system/
sudo systemctl daemon-reload

echo "== 6. caddy + sudoers =="
sudo cp infra/caddy/Caddyfile /etc/caddy/Caddyfile
sudo cp infra/sudoers-agency-executor /etc/sudoers.d/agency-executor
sudo visudo -cf /etc/sudoers.d/agency-executor   # refuse to continue if invalid

echo "== 7. crontab =="
crontab infra/cron/agency.crontab

echo "== 8. project repos =="
mkdir -p /home/agency/projects && cd /home/agency/projects
for r in hearth streamwise; do
  [ -d "$r" ] || git clone "https://github.com/itsbaldeep/$r.git"
done

echo "== 9. agency control-plane containers =="
# adjust paths if your compose files live elsewhere in the repo
find "$REPO" -maxdepth 2 -name 'docker-compose*.yml' -print
echo ">> bring up agency-postgres/clickhouse/dashboard from the compose files above"
echo ">> then restore data:  pg_restore -h 100.64.0.1 -U agency -d agencyos <latest.dump>"
echo ">> schema-only fallback: psql -h 100.64.0.1 -U agency -d agencyos -f infra/agencyos-schema.sql"

echo "== 10. start services =="
sudo systemctl enable --now agency-worker agency-bot opencode caddy

echo "BOOTSTRAP DONE — run infra/sync-system-state.sh and diff against git to verify parity."
