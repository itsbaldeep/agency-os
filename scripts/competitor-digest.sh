#!/bin/bash
# competitor-digest.sh — weekly Discord digest of new competitor content.
# Queries competitor_pages for pages first seen in the last 7 days,
# excluding the baseline bulk-insert. Posts one Discord message if rows exist.
set -e
PGHOST="100.64.0.1"
PGUSER="agency"
PGPW=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)
export PGPASSWORD="$PGPW"
WEBHOOK=$(grep DISCORD_WEBHOOK_URL /home/agency/agency-os/.env | cut -d= -f2)

ROWS=$(psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -F'\t' -c \
  "SELECT c.domain, p.url, COALESCE(p.title, p.url), p.lastmod, p.first_seen_at
   FROM competitor_pages p JOIN competitors c ON c.id=p.competitor_id
   WHERE c.scan_enabled=true
     AND p.first_seen_at > now() - interval '7 days'
     AND p.first_seen_at > (SELECT min(first_seen_at) + interval '1 hour'
                            FROM competitor_pages p2 WHERE p2.competitor_id = p.competitor_id)
   ORDER BY c.domain, p.first_seen_at DESC")

if [ -z "$ROWS" ]; then
  echo "no new competitor content this week"
  exit 0
fi

# Build Discord message, grouped by domain, cap 10 per domain, under 1900 chars.
MSG="📡 Competitor activity — last 7 days"
CURRENT_DOMAIN=""
DOMAIN_COUNT=0
LINE_COUNT=0
SKIPPED=0

while IFS=$'\t' read -r domain url title lastmod first_seen; do
  if [ "$domain" != "$CURRENT_DOMAIN" ]; then
    if [ -n "$CURRENT_DOMAIN" ] && [ "$SKIPPED" -gt 0 ]; then
      MSG="$MSG
…and $SKIPPED more"
    fi
    CURRENT_DOMAIN="$domain"
    DOMAIN_COUNT=0
    SKIPPED=0
    MSG="$MSG

**$domain**"
  fi
  DOMAIN_COUNT=$((DOMAIN_COUNT + 1))
  if [ "$DOMAIN_COUNT" -le 10 ]; then
    # Truncate title to 80 chars
    SHORT_TITLE="${title:0:80}"
    LINE="• ${SHORT_TITLE} — ${url}"
    # Check if adding this line would exceed 1900 chars
    if [ $((${#MSG} + ${#LINE} + 2)) -gt 1900 ]; then
      SKIPPED=$((SKIPPED + 1))
      continue
    fi
    MSG="${MSG}
${LINE}"
  else
    SKIPPED=$((SKIPPED + 1))
  fi
done <<< "$ROWS"

# Handle trailing "…and K more" for the last domain
if [ "$SKIPPED" -gt 0 ]; then
  MSG="$MSG
…and $SKIPPED more"
fi

# Post to Discord
ESCAPED_MSG=$(echo "$MSG" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
curl -sf --max-time 10 -H "Content-Type: application/json" \
  -d "{\"content\": $ESCAPED_MSG}" \
  "$WEBHOOK"

echo "digest posted to Discord"
