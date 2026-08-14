#!/bin/bash
# auto-merge.sh — merge green, unheld PRs by this account on our repos
ACCOUNT="itsbaldeep"
WEBHOOK=$(grep DISCORD_WEBHOOK_URL /home/agency/agency-os/.env | cut -d= -f2)

for REPO in agency-os agency-dashboard; do
  gh pr list --repo "itsbaldeep/$REPO" --json number,title,labels,createdAt,statusCheckRollup,author \
    -q '.[] | [.number, (if (.labels|length)==0 then "none" else (.labels|map(.name)|join(",")) end), .createdAt, .author.login, .title] | @tsv' \
  | while IFS=$'\t' read -r N LABELS CREATED AUTHOR TITLE; do
      [ "$AUTHOR" != "$ACCOUNT" ] && { echo "skip $REPO PR#$N: author $AUTHOR"; continue; }
      echo "$LABELS" | tr ',' '\n' | grep -qx "hold" && { echo "skip $REPO PR#$N: held"; continue; }
      CREATED_EPOCH=$(date -d "${CREATED/Z/+0000}" +%s)
      [ $(( $(date +%s) - CREATED_EPOCH )) -lt 300 ] && { echo "skip $REPO PR#$N: too new"; continue; }
      # Machine review (ensemble) before auto-merge — universal gate so even
      # externally-created PRs (like one pushed straight from an opencode
      # session) get reviewed. Applies a 'hold' label on any DEFECTS.
      if ! python3 /home/agency/agency-os/scripts/pr_review.py "$REPO" "$N"; then
        echo "skip $REPO PR#$N: machine review found defects (hold applied)"
        continue
      fi
      ALLOK=$(gh pr view "$N" --repo "itsbaldeep/$REPO" --json statusCheckRollup \
        -q '.statusCheckRollup | if length==0 then "false" else (map(if .__typename=="CheckRun" then .conclusion=="SUCCESS" else (.state=="SUCCESS") end) | all | tostring) end')
      [ "$ALLOK" != "true" ] && { echo "skip $REPO PR#$N: checks not all SUCCESS"; continue; }
      gh pr merge "$N" --repo "itsbaldeep/$REPO" --merge --delete-branch && echo "merged $REPO PR#$N: $TITLE" \
        && [ -n "$WEBHOOK" ] && curl -sf --max-time 10 -H "Content-Type: application/json" \
          -d "{ \"content\": \"🤖 auto-merged $REPO PR #$N: $TITLE\" }" "$WEBHOOK"
    done
done
exit 0
