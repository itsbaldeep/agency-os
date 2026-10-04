#!/bin/bash
# Collect only owner-opted-in brands. No publication, sending or deployment.
set -euo pipefail
exec python3 /home/agency/agency-os/scripts/queue-growth-measurement.py --configured
