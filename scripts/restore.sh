#!/bin/bash
# Restore from backup
set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <backup-directory>"
    echo "Available backups:"
    ls -td /opt/backups/bot-* 2>/dev/null | head -10
    exit 1
fi

BACKUP_DIR="$1"
if [ ! -d "$BACKUP_DIR" ]; then
    echo "Backup not found: $BACKUP_DIR"
    exit 1
fi

echo "Restoring from: $BACKUP_DIR"
cd /opt/bot
docker-compose down
cp -r "$BACKUP_DIR"/* .
docker-compose up -d
echo "Restore complete"
