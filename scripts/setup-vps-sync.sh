#!/bin/bash
# Setup VPS ↔ GitHub synchronization
set -e

echo "=== GRINCH-GRAM VPS Sync Setup ==="

# 1. Install dependencies
apt-get update
apt-get install -y python3-pip curl jq
pip3 install requests openai

# 2. Setup health monitor service
cp scripts/grinch-health.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable grinch-health.service
systemctl start grinch-health.service

# 3. Setup cron for error scanning
crontab -l 2>/dev/null | { cat; echo "*/5 * * * * cd /opt/bot && python3 scripts/scan_errors.py >> /var/log/grinch-errors.log 2>&1"; } | crontab -

# 4. Create log directory
mkdir -p /var/log/grinch

echo "=== Setup complete ==="
echo "Services:"
echo "  systemctl status grinch-health.service"
echo "Logs:"
echo "  journalctl -u grinch-health.service -f"
