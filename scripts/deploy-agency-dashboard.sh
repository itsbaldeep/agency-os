#!/bin/bash
# deploy-agency-dashboard.sh — companion to deploy-agency-os.sh, ships the dashboard
# as a docker service. Same self-healing contract: pull, build, run, verify, roll back.
set -uo pipefail
REPO="/home/agency/projects/agency-dashboard"
cd "$REPO"

notify() {  # best-effort Discord webhook, never fatal
  local msg="$1"
  local hook
  hook=$(grep '^DISCORD_WEBHOOK_URL=' "$REPO/.env" 2>/dev/null | cut -d= -f2-)
  [ -n "$hook" ] && curl -sf -X POST -H 'Content-Type: application/json' \
    -d "{\"content\": \"$msg\"}" "$hook" >/dev/null 2>&1
  echo "$msg"
}

git fetch origin --quiet || { echo "fetch failed"; exit 1; }
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && { echo "up to date"; exit 0; }

# refuse to deploy over local edits — they'd be silently clobbered
if [ -n "$(git status --porcelain)" ]; then
  notify "🚫 deploy skipped: uncommitted local changes in agency-dashboard (commit or stash them)"
  exit 1
fi

SUBJECT=$(git log -1 --format='%h %s' "$REMOTE")
git merge --ff-only origin/main --quiet || { notify "🚫 deploy failed: non-fast-forward"; exit 1; }

deploy() { docker compose -f "$REPO/docker-compose.yml" up -d --build dashboard; }

deploy || { git reset --hard "$LOCAL" --quiet; notify "🔥 deploy ROLLED BACK ($SUBJECT): build/up failed"; exit 1; }

# verify the container came up; if not, roll back to the previous commit and rebuild
sleep 3
if ! docker inspect -f '{{.State.Running}}' agency-dashboard 2>/dev/null | grep -q '^true$'; then
  git reset --hard "$LOCAL" --quiet
  deploy || notify "🔥 ROLLED BACK ($SUBJECT) but rebuild ALSO failed"
  notify "🔥 deploy ROLLED BACK ($SUBJECT): container agency-dashboard not running"
  exit 1
fi

notify "🚀 deployed agency-dashboard: $SUBJECT"
