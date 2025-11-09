#!/usr/bin/env bash
set -eu

# Helper to install the poller as a systemd service on Debian/Ubuntu.
# Run these commands as root (sudo) on the server. This script is a convenience
# — review before running. It assumes you placed the project under /var/lib/auto_notification

PROJECT_DIR=${PROJECT_DIR:-/var/lib/auto_notification}
SERVICE_NAME=${SERVICE_NAME:-auto_notification_poller}
ENV_FILE=/etc/default/auto_notification
UNIT_FILE=/etc/systemd/system/${SERVICE_NAME}.service

echo "This script will perform the following actions (review and run as root):"
echo " - create system user 'auto_notification' (if missing)"
echo " - copy environment example to ${ENV_FILE} (edit it for secrets)"
echo " - create systemd unit at ${UNIT_FILE}"
echo " - enable and start the service"
echo
read -p "Proceed? (y/N) " yn
if [[ "$yn" != "y" && "$yn" != "Y" ]]; then
  echo "Aborted"
  exit 1
fi

# create system user
if ! id -u auto_notification >/dev/null 2>&1; then
  useradd -r -s /usr/sbin/nologin -m -d ${PROJECT_DIR} auto_notification || true
  echo "Created user auto_notification"
else
  echo "User auto_notification exists"
fi

mkdir -p ${PROJECT_DIR}
chown -R auto_notification:auto_notification ${PROJECT_DIR}

if [[ ! -f ${ENV_FILE} ]]; then
  cp ${PROJECT_DIR}/scripts/auto_notification.env.example ${ENV_FILE}
  chmod 600 ${ENV_FILE}
  echo "Created ${ENV_FILE}; edit it to set SMTP_PASS and other secrets before starting the service."
else
  echo "${ENV_FILE} already exists — please verify it contains correct secrets and permissions."
fi

echo "Installing systemd unit..."
cat > ${UNIT_FILE} <<'UNIT'
[Unit]
Description=Auto Notification Poller
After=network.target

[Service]
Type=simple
User=auto_notification
WorkingDirectory=/var/lib/auto_notification
EnvironmentFile=/etc/default/auto_notification
ExecStart=/var/lib/auto_notification/.venv/bin/python /var/lib/auto_notification/scripts/poller.py
Restart=always
RestartSec=10
LimitNOFILE=4096
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

chmod 644 ${UNIT_FILE}
systemctl daemon-reload
systemctl enable --now ${SERVICE_NAME}.service
echo "Service ${SERVICE_NAME} enabled and started. Check status with: systemctl status ${SERVICE_NAME}.service"

echo "To view logs: sudo journalctl -u ${SERVICE_NAME}.service -f"
