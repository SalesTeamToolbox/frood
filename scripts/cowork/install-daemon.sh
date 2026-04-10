#!/usr/bin/env bash
# install-daemon.sh — Install the coworker daemon as a systemd service on the VPS.
#
# Run this ON the VPS (or via SSH):
#   ssh frood-prod "cd ~/frood && scripts/cowork/install-daemon.sh"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_USER="${DEPLOY_USER:-$(whoami)}"

SERVICE_NAME="frood-coworker"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Installing $SERVICE_NAME systemd service..."
echo "  Repo: $REPO_DIR"
echo "  User: $DEPLOY_USER"

# Create systemd unit
sudo tee "$SERVICE_FILE" > /dev/null <<UNITEOF
[Unit]
Description=Frood Coworker Daemon — autonomous Claude Code execution
After=network.target frood.service
Wants=frood.service

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/scripts/cowork/coworker-daemon.sh
Restart=on-failure
RestartSec=30

# Environment — inherit Claude Code auth from user profile
Environment=HOME=/home/$DEPLOY_USER
Environment=PATH=/home/$DEPLOY_USER/.local/bin:/usr/local/bin:/usr/bin:/bin

# Logging
StandardOutput=append:/var/log/frood-coworker.log
StandardError=append:/var/log/frood-coworker.log

# Resource limits
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
UNITEOF

# Set up log rotation
sudo tee /etc/logrotate.d/frood-coworker > /dev/null <<LOGEOF
/var/log/frood-coworker.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
LOGEOF

# Ensure scripts are executable
chmod +x "$REPO_DIR/scripts/cowork/"*.sh
chmod +x "$REPO_DIR/scripts/auto-resume.sh"

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

echo ""
echo "Done! Service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager -l
echo ""
echo "Commands:"
echo "  sudo systemctl status $SERVICE_NAME   # Check status"
echo "  sudo systemctl stop $SERVICE_NAME     # Stop daemon"
echo "  sudo systemctl restart $SERVICE_NAME  # Restart daemon"
echo "  tail -f /var/log/frood-coworker.log # Watch logs"
