#!/bin/bash
# --------------------------------------------------------------------------
#  recover-from-github.sh
#  Emergency recovery: restore /opt/bot from origin/main WITHOUT stopping
#  the running Docker container.
#
#  Use case: local working tree is corrupted (deleted files, missing
#  Dockerfile/docker-compose.yml) but the container image in memory is
#  healthy.
#
#  Usage (run as root on VPS):
#     bash /opt/bot/scripts/recover-from-github.sh
#
#  Safe to run while quantum-bot is running -- the container is NOT touched.
# --------------------------------------------------------------------------
set -euo pipefail

# -- Configuration ----------------------------------------------------------
REPO_URL="${REPO_URL:-https://github.com/Alexkkkkk/grinch-gram-ton.git}"
BOT_DIR="${BOT_DIR:-/opt/bot}"
TEMP_DIR=$(mktemp -d /tmp/bot-recover-XXXXXX)
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

# -- Pre-flight checks ------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo >&2 "[ERROR] Must run as root."
    exit 1
fi
if ! command -v git &>/dev/null; then
    echo >&2 "[ERROR] git not installed."
    exit 1
fi
if ! command -v docker &>/dev/null; then
    echo >&2 "[ERROR] docker not installed."
    exit 1
fi

# -- Container health check -------------------------------------------------
echo "[1/6] Checking running container..."
if docker ps --format '{{.Names}}' | grep -qx 'quantum-bot'; then
    echo "  OK  quantum-bot is RUNNING (will NOT be stopped)"
else
    echo "  WARN quantum-bot is NOT running"
fi

# -- Preserve runtime data --------------------------------------------------
echo "[2/6] Preserving runtime data..."
mkdir -p "${BOT_DIR}/data" "${BOT_DIR}/backups" "${BOT_DIR}/logs"
if [[ -f "${BOT_DIR}/.env" ]]; then
    cp "${BOT_DIR}/.env" "${TEMP_DIR}/.env.backup"
    echo "  OK  .env backed up"
else
    echo "  WARN .env not found"
fi

# -- Clone fresh code -------------------------------------------------------
echo "[3/6] Cloning fresh code from GitHub..."
git clone --depth 1 --single-branch --branch main "${REPO_URL}" "${TEMP_DIR}/repo"
echo "  OK  Cloned to ${TEMP_DIR}/repo"

# -- Copy over broken tree --------------------------------------------------
echo "[4/6] Restoring files to ${BOT_DIR}..."
if command -v rsync &>/dev/null; then
    rsync -a --delete \
        --exclude='.git' --exclude='data' --exclude='backups' \
        --exclude='logs' --exclude='.env' \
        "${TEMP_DIR}/repo/" "${BOT_DIR}/"
else
    for item in "${TEMP_DIR}/repo"/* "${TEMP_DIR}/repo"/.[^.]*; do
        [[ -e "${item}" ]] || continue
        bn=$(basename "${item}")
        case "${bn}" in
            data|backups|logs|.env|.git) continue ;;
        esac
        rm -rf "${BOT_DIR}/${bn}" 2>/dev/null || true
        cp -r "${item}" "${BOT_DIR}/"
    done
fi

if [[ -f "${TEMP_DIR}/.env.backup" ]]; then
    cp "${TEMP_DIR}/.env.backup" "${BOT_DIR}/.env"
    echo "  OK  .env restored"
fi
chmod +x "${BOT_DIR}/scripts/"*.sh "${BOT_DIR}/scripts/"*.py 2>/dev/null || true
echo "  OK  Files restored"

# -- Git verification -------------------------------------------------------
echo "[5/6] Verifying Git state..."
cd "${BOT_DIR}"
git fetch origin main --depth 1
git reset --hard origin/main
git clean -fd
echo "  OK  Working tree matches origin/main"

# -- Post-recovery checks ---------------------------------------------------
echo "[6/6] Post-recovery checks..."
missing=()
for required in Dockerfile docker-compose.yml main.py grid_trader.py; do
    if [[ ! -f "${BOT_DIR}/${required}" ]]; then
        missing+=("${required}")
    fi
done
if [[ ${#missing[@]} -eq 0 ]]; then
    echo "  OK  All critical files present"
else
    echo "  FAIL MISSING: ${missing[*]}"
    exit 1
fi

if docker-compose config &>/dev/null; then
    echo "  OK  docker-compose.yml syntax OK"
else
    echo "  WARN docker-compose config check failed"
fi

echo ""
echo "=========================================="
echo "  RECOVERY COMPLETE"
echo "=========================================="
echo "  quantum-bot was NOT restarted."
echo "  To rebuild when ready:"
echo "    cd /opt/bot"
echo "    docker-compose build --no-cache bot"
echo "    docker-compose up -d --force-recreate bot"
echo "=========================================="
