Deployment helper files included in `scripts/`:

- install_cron.sh
  - Helper script to add a crontab entry that runs `scripts/run_notify.py` every minute.
  - Edit `PROJECT_DIR` or run from repo root; ensure `.venv` exists and Playwright browsers are installed.

- run_notify.service / run_notify.timer
  - Templates to set up a systemd oneshot service and timer that run the runner every minute.
  - Copy to `/etc/systemd/system/` and enable with `systemctl enable --now run_notify.timer`.

- logrotate_auto_notification
  - Example logrotate config to rotate `cron.log`, `notification.log`, and `notifications.jsonl`.
  - Copy to `/etc/logrotate.d/auto_notification` and adjust paths/owner as needed.

- .env.example
  - Example environment variables for SMTP and basic options. Do NOT commit secrets.

Quick start (cron):
1. Create and activate venv, install deps & Playwright browsers:
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m playwright install --with-deps

2. Edit .env (or export env vars) with SMTP settings.

3. Make install script executable and run it:
   chmod +x scripts/install_cron.sh
   bash scripts/install_cron.sh

4. Check cron.log for output and notifications.jsonl for history.

If you prefer systemd timers, copy the service/timer templates to /etc/systemd/system, then run:
  sudo systemctl daemon-reload
  sudo systemctl enable --now run_notify.timer

