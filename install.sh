#!/usr/bin/env bash
# install.sh — deploy ping-watchdog to /opt and register it as a systemd service
# Run as root: sudo bash install.sh

set -euo pipefail

DEPLOY_DIR="/opt/ping-watchdog"
SERVICE_NAME="ping-watchdog"
SERVICE_FILE="ping-watchdog.service"

# ── 1. Verify root ──────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo bash install.sh)" >&2
    exit 1
fi

# ── 2. Install uv for root (if not already present) ─────────────────────────
if ! command -v /root/.local/bin/uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="/root/.local/bin:$PATH"
fi

# ── 3. Copy project files ────────────────────────────────────────────────────
echo "Deploying project to ${DEPLOY_DIR}..."
mkdir -p "$DEPLOY_DIR"
cp ping_watchdog.py pyproject.toml "$DEPLOY_DIR/"

# ── 4. Create the uv virtual environment & sync ──────────────────────────────
echo "Creating virtual environment with uv..."
cd "$DEPLOY_DIR"
/root/.local/bin/uv sync

# ── 5. Register the systemd service ─────────────────────────────────────────
echo "Installing systemd service..."
cp "$OLDPWD/$SERVICE_FILE" "/etc/systemd/system/$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
echo "Done!  Service status:"
systemctl status "$SERVICE_NAME" --no-pager || true
echo ""
echo "Useful commands:"
echo "  journalctl -u $SERVICE_NAME -f          # live logs"
echo "  systemctl status $SERVICE_NAME          # status"
echo "  systemctl stop $SERVICE_NAME            # stop"
echo "  systemctl disable $SERVICE_NAME         # disable on boot"
