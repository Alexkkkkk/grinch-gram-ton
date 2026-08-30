#!/bin/bash
# Automated backup script
set -e

BACKUP_DIR="/opt/backups/bot-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

cd /opt/bot
cp -r . "$BACKUP_DIR/"

# Keep only last 10 backups
ls -td /opt/backups/bot-* | tail -n +11 | xargs rm -rf 2>/dev/null || true

echo "Backup created: $BACKUP_DIR"
