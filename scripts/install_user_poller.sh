#!/usr/bin/env bash
set -euo pipefail

# User-mode installer for auto_notification poller.
# This tries to install into the current user's home (~) and register a systemd --user service.
# It does NOT require sudo. It may still fail if Playwright native deps are missing; in that
# case you need to install system packages (see README) or use the root installer.

# Usage: from project root
#   bash scripts/install_user_poller.sh

PROJECT_DIR=$(pwd)
VENV_DIR=${PROJECT_DIR}/.venv
SYSTEMD_USER_DIR=${HOME}/.config/systemd/user
ENV_FILE=${HOME}/.config/auto_notification/env
SERVICE_NAME=auto_notification_poller.service

echo "Installing auto_notification poller in user mode"
echo "Project dir: ${PROJECT_DIR}"
echo

echo "1) Create virtualenv (if missing)"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --upgrade pip
if [[ -f "${PROJECT_DIR}/requirements.txt" ]]; then
  "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
else
  echo "No requirements.txt found; installing playwright only"
  "${VENV_DIR}/bin/pip" install playwright
fi

echo
echo "2) Install Playwright browser binaries (this downloads to user profile)"
"${VENV_DIR}/bin/python" -m playwright install chromium || true

echo
echo "3) Create user systemd unit directory"
mkdir -p "${SYSTEMD_USER_DIR}"

echo "4) Create environment file (examples copied). Edit ${ENV_FILE} and set SMTP_PASS etc before enabling the service."
mkdir -p "$(dirname "${ENV_FILE}")"
if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'ENV'
# User env for auto_notification poller (do NOT commit secrets)
# Copy and edit values below
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your_app_password_here
FROM_EMAIL=your@gmail.com
POLL_INTERVAL=60
ENV
  chmod 600 "${ENV_FILE}"
  echo "Wrote example env to ${ENV_FILE} (please edit and fill secrets)"
else
  echo "Env file ${ENV_FILE} already exists; please ensure it contains correct secrets and permission 600"
fi

echo
echo "5) Create systemd --user unit"
cat > "${SYSTEMD_USER_DIR}/${SERVICE_NAME}" <<EOF
[Unit]
Description=Auto Notification Poller (user)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python ${PROJECT_DIR}/scripts/poller.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

echo "6) Reload and enable user service"
systemctl --user daemon-reload
systemctl --user enable --now ${SERVICE_NAME}

echo
echo "Installation complete. To see logs run:"
echo "  journalctl --user -u ${SERVICE_NAME} -f"
echo
echo "Notes:"
echo " - If 'systemctl --user' fails, your system may not have a user systemd session (common in some containers)."
echo " - Playwright may require extra system packages on Linux. If the poller fails to start with browser errors, use the root installer or install required packages listed in README."
