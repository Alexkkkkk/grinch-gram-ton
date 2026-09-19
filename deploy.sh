#!/bin/bash
# -*- mode: sh; sh-shell: bash -*-
#--------------------------------------------------------------------------
#  deploy.sh — Safe auto-deploy from GitHub (hardened)
#
#  Called by cron every 3 minutes AND by .github/workflows/deploy.yml.
#  Guarantees:
#    * single-flight  — flock, so cron and Actions never deploy at once
#    * hard sync      — git reset --hard, so a dirty tree cannot stall deploys
#    * cached build   — no --no-cache (a full rebuild on 2 vCPU takes minutes)
#    * health gate    — verifies the app answers before declaring success
#    * auto rollback  — restores the previous commit if the health gate fails
#
#  Usage: bash /opt/bot/deploy.sh
#--------------------------------------------------------------------------
set -euo pipefail

BOT_DIR=${BOT_DIR:-/opt/bot}
CONTAINER=${CONTAINER:-quantum-bot}
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:3000/api/health}
LOCK_FILE=${LOCK_FILE:-/run/lock/grinch-deploy.lock}
HEALTH_RETRIES=${HEALTH_RETRIES:-30}

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

# ── Single-flight lock ────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOCK_FILE")"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log "Another deploy is already running. Exiting."
    exit 0
fi

cd "$BOT_DIR"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    log "[ERROR] Container $CONTAINER not running, skipping deploy"
    exit 1
fi

PREV_SHA=$(git rev-parse HEAD)

git fetch origin main --depth 1
REMOTE=$(git rev-parse origin/main)

if [ "$PREV_SHA" = "$REMOTE" ]; then
    log "Up to date ($REMOTE)"
    exit 0
fi

# ── Hard sync: a dirty working tree must never block or corrupt a deploy ───────
log "Deploying ${PREV_SHA:0:8} -> ${REMOTE:0:8}"
git reset --hard "$REMOTE"

deploy_sha() {
    export GIT_SHA="$1"
    docker compose build bot
    docker compose up -d --force-recreate bot
}

wait_healthy() {
    local i
    for i in $(seq 1 "$HEALTH_RETRIES"); do
        if curl -fsS -m 5 "$HEALTH_URL" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

deploy_sha "$REMOTE"

# ── Health gate + automatic rollback ─────────────────────────────────────────
if wait_healthy; then
    log "Deployed OK to ${REMOTE:0:8} (healthy within ${HEALTH_RETRIES}s)"
    exit 0
fi

log "[ERROR] Health check failed after ${HEALTH_RETRIES}s — rolling back to ${PREV_SHA:0:8}"
git reset --hard "$PREV_SHA"
deploy_sha "$PREV_SHA"

if wait_healthy; then
    log "Rollback to ${PREV_SHA:0:8} complete (service restored)"
else
    log "[FATAL] Rollback to ${PREV_SHA:0:8} did not become healthy — manual intervention required"
fi
exit 1
