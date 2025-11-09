#!/usr/bin/env bash
# Install a crontab entry to run the project's notify runner every minute.
# Usage: edit the PROJECT_DIR and VENV_PATH below if needed, then run:
#   bash scripts/install_cron.sh

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="${PROJECT_DIR}/.venv"
LOGFILE="${PROJECT_DIR}/cron.log"

# The command cron will run. Adjust python path if you use system python.
CMD="cd ${PROJECT_DIR} && . ${VENV_PATH}/bin/activate && /usr/bin/env python ${PROJECT_DIR}/scripts/run_notify.py >> ${LOGFILE} 2>&1"

# Cron line (run every minute)
CRON_LINE="* * * * * ${CMD}"

echo "Installing crontab entry (will preserve existing crontab entries)..."
# Install the new crontab line if it's not already present
( crontab -l 2>/dev/null || true ) | grep -F "${CMD}" >/dev/null 2>&1 || (
  ( crontab -l 2>/dev/null || true; echo "${CRON_LINE}" ) | crontab -
)

echo "Done. Crontab updated. Log file: ${LOGFILE}"

echo "To remove, run: crontab -l | grep -v -F \"${CMD}\" | crontab -"