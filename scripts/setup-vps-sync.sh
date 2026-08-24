#!/bin/bash
# Setup VPS ↔ GitHub Super Sync with Full Autonomy
set -e

echo "=========================================="
echo "  GRINCH-GRAM v3.1 Super Autonomy Setup"
echo "=========================================="

# 1. Install dependencies
echo "[1/8] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq python3-pip curl jq htop iotop
pip3 install -q requests openai psutil 2>/dev/null || true

# 2. Create directories
echo "[2/8] Creating directories..."
mkdir -p /opt/bot/data
mkdir -p /opt/backups
mkdir -p /var/log/grinch
mkdir -p /opt/bot/fixes

# 3. Setup health monitor
echo "[3/8] Setting up health monitor..."
cp /opt/bot/scripts/grinch-health.service /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload
systemctl enable grinch-health.service 2>/dev/null || true
systemctl start grinch-health.service 2>/dev/null || true

# 4. Setup supervisor (autonomy engine)
echo "[4/8] Setting up autonomy supervisor..."
cp /opt/bot/scripts/grinch-supervisor.service /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload
systemctl enable grinch-supervisor.service 2>/dev/null || true
systemctl start grinch-supervisor.service 2>/dev/null || true

# 5. Setup cron jobs
echo "[5/8] Setting up cron jobs..."
(crontab -l 2>/dev/null | grep -v "grinch" || true) > /tmp/grinch-cron
cat >> /tmp/grinch-cron << 'CRON'
# GRINCH-GRAM Autonomy
*/5 * * * * cd /opt/bot && python3 scripts/scan_errors.py >> /var/log/grinch/scan-errors.log 2>&1
*/10 * * * * cd /opt/bot && python3 -c "from autonomy.auto_updater import AutoUpdater; AutoUpdater().check_for_updates()" >> /var/log/grinch/updater.log 2>&1
0 */6 * * * cd /opt/bot && docker system prune -f >> /var/log/grinch/docker-prune.log 2>&1
CRON
crontab /tmp/grinch-cron
rm /tmp/grinch-cron

# 6. Setup logrotate
echo "[6/8] Setting up logrotate..."
cat > /etc/logrotate.d/grinch << 'LOGROTATE'
/var/log/grinch/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
LOGROTATE

# 7. Fix permissions
echo "[7/8] Fixing permissions..."
chown -R root:root /opt/bot
chmod -R 755 /opt/bot/scripts
chmod +x /opt/bot/scripts/*.py /opt/bot/scripts/*.sh 2>/dev/null || true

# 8. Verify
echo "[8/8] Verifying setup..."
echo "Services:"
systemctl is-active grinch-health.service 2>/dev/null && echo "  ✓ health monitor" || echo "  ✗ health monitor (check manually)"
systemctl is-active grinch-supervisor.service 2>/dev/null && echo "  ✓ supervisor" || echo "  ✗ supervisor (check manually)"

echo ""
echo "=========================================="
echo "  ✅ Super Autonomy Setup Complete!"
echo "=========================================="
echo ""
echo "Commands:"
echo "  systemctl status grinch-supervisor.service"
echo "  systemctl status grinch-health.service"
echo "  journalctl -u grinch-supervisor -f"
echo "  tail -f /var/log/grinch/supervisor.log"
echo ""
echo "Autonomy features:"
echo "  • Self-healing (restart bot if down)"
echo "  • Performance monitoring (CPU/RAM/Disk)"
echo "  • Auto-updates (check every 6 hours)"
echo "  • Error scanning (every 5 minutes)"
echo "  • Intelligence Engine (ML error analysis)"
echo "  • Auto-fix PRs (GitHub Actions + OpenAI)"
echo "  • Health checks (every 15 minutes)"
