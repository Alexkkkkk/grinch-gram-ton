#!/bin/bash
set -euo pipefail

PROJECT_DIR="/opt/bot"
LOG_FILE="/var/log/grinch-deploy.log"
LOCK_FILE="/tmp/grinch-deploy.lock"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# Prevent parallel builds
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log "ERROR: Another deploy is running. Exiting."
    exit 1
fi

cd "$PROJECT_DIR"

# Check disk space
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 85 ]; then
    log "WARNING: Disk usage ${DISK_USAGE}%. Cleaning up..."
    docker builder prune -f
    docker system prune -f --volumes=false
    docker image prune -af
fi

# Check if build is already running
if pgrep -f "docker compose build" > /dev/null; then
    log "WARNING: Build already in progress. Waiting..."
    while pgrep -f "docker compose build" > /dev/null; do
        sleep 10
    done
fi

# Pull latest code
log "Fetching latest code..."
git fetch origin
NEW=$(git rev-parse origin/main)
CURRENT=$(git rev-parse HEAD)

if [ "$NEW" = "$CURRENT" ]; then
    log "Already up-to-date ($CURRENT)."
    exit 0
fi

log "Updating $CURRENT -> $NEW"
git reset --hard origin/main

# Build with cleanup
log "Building Docker image..."
docker compose down
docker compose build --no-cache
docker compose up -d

# Verify
sleep 5
if docker compose ps | grep -q "Up"; then
    log "SUCCESS: Deployed $NEW"
    # Smoke test inside container
    docker compose exec -T bot python scripts/ci_smoke.py >> "$LOG_FILE" 2>&1 || true
else
    log "ERROR: Containers failed to start!"
    exit 1
fi

# Cleanup old images
log "Cleaning up old images..."
docker image prune -af --filter "until=24h" >> "$LOG_FILE" 2>&1 || true

log "Deploy finished."
