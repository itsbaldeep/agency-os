#!/bin/bash
# deploy-agency-os.sh — the self-hosting leg. Runs as background job every 2 min.
# If origin/main moved: pull, compile-check, restart services. On any failure:
# roll back to the previous commit and restart, so the system can't brick itself.
set -uo pipefail
REPO="/home/agency/agency-os"
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
SUBJECT=$(git log -1 --format='%h %s' "$REMOTE")

# uncommitted local edits: auto-commit pure mode changes / infra/ drift,
# but refuse to deploy over any other edits — they'd be silently clobbered
if [ -n "$(git status --porcelain)" ]; then
  AUTO=1
  while IFS= read -r line; do
    code="${line:0:2}"
    path="${line:3}"
    case "$path" in infra/*) continue;; esac
    if [ "$code" = "??" ]; then AUTO=0; break; fi           # untracked outside infra/
    [ -n "$(git diff --numstat -- "$path")" ] && { AUTO=0; break; }  # real content change
  done < <(git status --porcelain)
  if [ "$AUTO" = 1 ]; then
    git add -A && git commit -m "auto: state drift" --quiet && git push --quiet
  else
    notify "🚫 deploy skipped: uncommitted local changes in agency-os (commit or stash them)"
    exit 1
  fi
fi

MERGED=0
if [ "$LOCAL" != "$REMOTE" ]; then
  git merge --ff-only origin/main --quiet || { notify "🚫 deploy failed: non-fast-forward"; exit 1; }
  chmod +x scripts/*.sh

  # compile gate: never restart into broken python
  if ! python3 -m py_compile scripts/worker.py scripts/*.py 2>/tmp/deploy-err.txt || \
     ! bot/.venv/bin/python -m py_compile bot/agency_bot.py 2>>/tmp/deploy-err.txt; then
    git reset --hard "$LOCAL" --quiet
    notify "🔥 deploy ROLLED BACK ($SUBJECT): compile error — $(head -c 300 /tmp/deploy-err.txt)"
    exit 1
  fi
  MERGED=1
fi

# restart when newly merged, or when the running worker predates the last change to scripts/ or bot/
NEED=0
if [ "$MERGED" = 1 ]; then
  NEED=1
else
  LAST=$(git log -1 --format=%ct -- scripts/ bot/)
  if [ -n "$LAST" ]; then
    WORKER_START=$(systemctl show agency-worker -p ActiveEnterTimestamp --value)
    [ -n "$WORKER_START" ] && [ "$(date -d "$WORKER_START" +%s)" -lt "$LAST" ] && NEED=1
  fi
fi
[ "$NEED" = 0 ] && { echo "up to date"; exit 0; }

# drain: give in-flight tasks up to 3 min to finish before restarting
DRAIN_NOTE=""
if [ -n "$(grep POSTGRES_PASSWORD "$REPO/.env" 2>/dev/null)" ]; then
  export PGPASSWORD=$(grep POSTGRES_PASSWORD "$REPO/.env" | cut -d= -f2)
  for _ in $(seq 1 18); do
    N=$(psql -h 100.64.0.1 -U agency -d agencyos -t -A -c \
        "SELECT count(*) FROM tasks WHERE status='running'" 2>/dev/null)
    [ -z "$N" ] || [ "$N" = "0" ] && { N=""; break; }  # DB down or idle: don't hold the restart
    sleep 10
  done
  [ -n "$N" ] && DRAIN_NOTE=" ⚠ $N task(s) still running after 180s — restarted anyway"
fi

sudo /usr/bin/systemctl restart agency-worker agency-bot

# verify both came up; if not, roll back and restart again
sleep 3
if ! systemctl is-active --quiet agency-worker || ! systemctl is-active --quiet agency-bot; then
  [ "$MERGED" = 1 ] && git reset --hard "$LOCAL" --quiet
  sudo /usr/bin/systemctl restart agency-worker agency-bot
  notify "🔥 deploy ROLLED BACK ($SUBJECT): service failed to start"
  exit 1
fi

notify "🚀 deployed agency-os: $SUBJECT$DRAIN_NOTE"
