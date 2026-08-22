#!/bin/bash
# Compatibility entrypoint for background job 4.
set -euo pipefail
exec python3 /home/agency/agency-os/scripts/ops.py backup
