#!/usr/bin/env bash
set -euo pipefail
# start_poller.sh - wrapper to keep poller running in user mode
# Place this in the project root and run under tmux or nohup.

cd "$(dirname "$0")"
# load env if present
if [ -f "$HOME/.config/auto_notification/env" ]; then
  set -a
  . "$HOME/.config/auto_notification/env"
  set +a
fi
export PYTHONPATH="$(pwd)"

# loop-run poller (poller itself will retry browser creation on errors)
while true; do
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting poller" >> poller.log
  ./.venv/bin/python ./scripts/poller.py >> poller.log 2>&1 || true
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] poller exited; restarting in 5s" >> poller.log
  sleep 5
done
