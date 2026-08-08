#!/bin/bash
# self-review.sh — enqueue a self_review task for the worker
# Inserts a row into tasks with type='self_review' and exits.
set -e

PGHOST="100.64.0.1"
PGUSER="agency"
PGPW=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)
export PGPASSWORD="$PGPW"

psql -h "$PGHOST" -U "$PGUSER" -d agencyos -t -A -c \
  "INSERT INTO tasks (type, triggered_by) VALUES ('self_review', 'scheduled') RETURNING id"
