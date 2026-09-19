#!/bin/bash
# -*- mode: sh; sh-shell: bash -*-
#--------------------------------------------------------------------------
#  cleanup-vps-artifacts.sh — housekeeping for /opt/bot
#
#  The VPS working tree had accumulated hand-made backups, seven of which were
#  copies of .env containing TON_MNEMONIC / SECRET_KEY in cleartext.
#
#  This archives (never deletes) them into a dated, mode-600 directory and
#  tightens permissions on the live .env. Dry-run by default.
#
#  Usage:  bash scripts/cleanup-vps-artifacts.sh          # preview
#          APPLY=1 bash scripts/cleanup-vps-artifacts.sh  # archive for real
#--------------------------------------------------------------------------
set -euo pipefail

BOT_DIR=${BOT_DIR:-/opt/bot}
STAMP=$(date '+%Y%m%d-%H%M%S')
ARCHIVE="$BOT_DIR/.artifact-archive/$STAMP"
APPLY=${APPLY:-0}

cd "$BOT_DIR"

echo "==> Files matching backup/bak patterns:"
mapfile -t FILES < <(find . -maxdepth 3 \
    \( -name '*.bak' -o -name '*.bak-*' -o -name '*.pre-*' -o -name '*.backup*' \
       -o -name 'Dockerfile.pre-*' -o -name '.env.bak*' -o -name '.env.pre-*' \) \
    -not -path './.git/*' -type f | sort)

if [ ${#FILES[@]} -eq 0 ]; then
    echo "    (none)"
else
    printf '    %s\n' "${FILES[@]}"
    echo "    total: ${#FILES[@]}"
fi

if [ "$APPLY" != "1" ]; then
    echo
    echo "==> DRY RUN. Re-run with APPLY=1 to archive these files."
else
    if [ ${#FILES[@]} -gt 0 ]; then
        install -d -m 700 "$ARCHIVE"
        printf '    archived to %s\n' "$ARCHIVE"
        for f in "${FILES[@]}"; do
            install -d -m 700 "$ARCHIVE/$(dirname "$f")"
            mv "$f" "$ARCHIVE/$f"
        done
        # The archive may contain .env copies -> seal it
        chmod -R go-rwx "$ARCHIVE"
    fi
fi

echo
echo "==> Permissions on live secrets"
for f in .env .env.local; do
    if [ -f "$f" ]; then
        if [ "$APPLY" = "1" ]; then
            chmod 600 "$f"
            echo "    chmod 600 $f"
        else
            printf '    %s -> %s (would become 600)\n' "$f" "$(stat -c '%a' "$f")"
        fi
    fi
done

echo
echo "==> Docker logs / build cache footprint"
docker system df 2>/dev/null || echo "    docker not available"

echo
echo "==> Done."
