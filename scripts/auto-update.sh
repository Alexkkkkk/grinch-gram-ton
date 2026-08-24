#!/bin/bash
set -euo pipefail

PROJECT_DIR="/opt/bot"
LOG_FILE="/var/log/grinch-auto-update.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

cd "$PROJECT_DIR"

# Check disk before anything
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 80 ]; then
    log "Disk ${DISK_USAGE}% full. Running cleanup..."
    docker builder prune -f
    docker system prune -f --volumes=false
    docker image prune -af
fi

git fetch origin
NEW=$(git rev-parse origin/main)
CURRENT=$(git rev-parse HEAD)

if [ "$NEW" = "$CURRENT" ]; then
    exit 0
fi

log "New commit detected: $NEW"
exec "$PROJECT_DIR/scripts/deploy.sh"
