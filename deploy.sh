#!/bin/bash
# GRINCH-GRAM — Auto-deploy script (запускается cron'ом каждые 3 минуты)
# ⚠️  ЭТОТ СКРИПТ НИКОГДА НЕ БЛОКИРУЕТ SSH — только восстанавливает доступ.
# Путь на VPS: /opt/bot/deploy.sh
# Cron: */3 * * * * /bin/bash /opt/bot/deploy.sh >> /opt/bot/deploy.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

TS() { date '+%F %T'; }

BOT_DIR="/opt/bot"
LOG="$BOT_DIR/deploy.log"
LOCK="$BOT_DIR/.deploy.lock"
MAX_LOG_LINES=1000

cd "$BOT_DIR"

# ── Ротация лога ──────────────────────────────────────────────────────────────
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt "$MAX_LOG_LINES" ]; then
    tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# ── Lock — защита от параллельных запусков ────────────────────────────────────
if [ -f "$LOCK" ]; then
    LOCK_PID=$(cat "$LOCK" 2>/dev/null || echo "0")
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[$(TS)] SKIP: другой деплой уже запущен (PID=$LOCK_PID)" >> "$LOG"
        exit 0
    fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# ═══════════════════════════════════════════════════════════════════════════════
# SSH-ЗАЩИТА: скрипт НИКОГДА не отключает парольный вход и root.
# Только проверяет, что они включены, и восстанавливает при необходимости.
# Бэкап конфига создаётся перед любыми изменениями.
# ═══════════════════════════════════════════════════════════════════════════════
_SSH_BACKUP="/etc/ssh/sshd_config.deploy.bak"
_ssh_changed=0

# Бэкапим оригинал (один раз, при первом запуске)
[ -f "$_SSH_BACKUP" ] || cp "/etc/ssh/sshd_config" "$_SSH_BACKUP"

_ensure_ssh_line() {
    local file="$1"
    local key="$2"
    local value="$3"
    # Если строка существует и уже правильная — ничего не делаем
    if grep -qE "^[[:space:]]*${key}[[:space:]]+${value}[[:space:]]*$" "$file" 2>/dev/null; then
        return 0
    fi
    # Если строка существует, но неправильная — исправляем
    if grep -qiE "^[[:space:]]*#?[[:space:]]*${key}[[:space:]]+" "$file" 2>/dev/null; then
        sed -i -E "s/^[[:space:]]*#?[[:space:]]*${key}[[:space:]]+.*/${key} ${value}/" "$file"
        _ssh_changed=1
    else
        # Строки нет — добавляем в конец
        echo "${key} ${value}" >> "$file"
        _ssh_changed=1
    fi
}

_ensure_ssh_line "/etc/ssh/sshd_config" "PasswordAuthentication" "yes"
_ensure_ssh_line "/etc/ssh/sshd_config" "PermitRootLogin" "yes"

# Проверяем override-файл
_SSH_OVERRIDE="/etc/ssh/sshd_config.d/00-deploy-access.conf"
if [ -d "/etc/ssh/sshd_config.d" ]; then
    if ! grep -qE "^[[:space:]]*PasswordAuthentication[[:space:]]+yes" "$_SSH_OVERRIDE" 2>/dev/null || \
       ! grep -qE "^[[:space:]]*PermitRootLogin[[:space:]]+yes" "$_SSH_OVERRIDE" 2>/dev/null; then
        cat > "$_SSH_OVERRIDE" <<'SSHEOF'
# GRINCH-GRAM deploy.sh — SSH protection override
# Этот файл гарантирует, что парольный вход и root доступ НЕ отключаются.
# Если вы хотите изменить эти настройки — отредактируйте /etc/ssh/sshd_config
# и удалите этот файл.
PasswordAuthentication yes
PermitRootLogin yes
SSHEOF
        _ssh_changed=1
    fi
    # Проверяем, что sshd_config.d/*.conf не отключает доступ
    for _f in /etc/ssh/sshd_config.d/*.conf; do
        [ -f "$_f" ] || continue
        if grep -qiE "^[[:space:]]*PasswordAuthentication[[:space:]]+no" "$_f" 2>/dev/null; then
            sed -i -E 's/^[[:space:]]*#?[[:space:]]*PasswordAuthentication[[:space:]]+.*/PasswordAuthentication yes/' "$_f"
            _ssh_changed=1
        fi
        if grep -qiE "^[[:space:]]*PermitRootLogin[[:space:]]+no" "$_f" 2>/dev/null; then
            sed -i -E 's/^[[:space:]]*#?[[:space:]]*PermitRootLogin[[:space:]]+.*/PermitRootLogin yes/' "$_f"
            _ssh_changed=1
        fi
    done
fi

# Перезагружаем sshd ТОЛЬКО если что-то изменилось и конфиг валиден
if [ "$_ssh_changed" = "1" ]; then
    if sshd -t 2>/dev/null; then
        systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || service ssh reload 2>/dev/null || true
        echo "[$(TS)] 🔧 SSH: пароль + root доступ защищён и активен" >> "$LOG"
    else
        # Конфиг сломан — откатываем бэкап
        cp "$_SSH_BACKUP" "/etc/ssh/sshd_config"
        rm -f "$_SSH_OVERRIDE" 2>/dev/null || true
        sshd -t 2>/dev/null && (systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true)
        echo "[$(TS)] 🚨 SSH: конфиг был сломан — выполнен откат из бэкапа" >> "$LOG"
    fi
fi

# ── Аварийный запуск sshd (если служба упала) ───────────────────────────────
_ssh_active=0
systemctl is-active --quiet ssh  2>/dev/null && _ssh_active=1
systemctl is-active --quiet sshd 2>/dev/null && _ssh_active=1
if [ "$_ssh_active" = "0" ]; then
    if sshd -t 2>/dev/null; then
        systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || true
        echo "[$(TS)] 🔄 SSH: служба была остановлена — выполнен restart" >> "$LOG"
    else
        # Конфиг сломан — откатываем и пробуем снова
        cp "$_SSH_BACKUP" "/etc/ssh/sshd_config"
        rm -f "$_SSH_OVERRIDE" 2>/dev/null || true
        sshd -t 2>/dev/null && systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true
        echo "[$(TS)] 🚨 SSH: откат + аварийный restart после падения службы" >> "$LOG"
    fi
fi

# ── Алерт переполнения диска (>85% → очистка) ─────────────────────────────────
DISK_PCT=$(df / --output=pcent | tail -1 | tr -d ' %')
if [ "$DISK_PCT" -ge 85 ]; then
    echo "[$(TS)] 🚨 ДИСК ${DISK_PCT}% — экстренная очистка build cache!" >> "$LOG"
    docker builder prune -f >> "$LOG" 2>&1
    docker image prune -f   >> "$LOG" 2>&1
    DISK_PCT_AFTER=$(df / --output=pcent | tail -1 | tr -d ' %')
    echo "[$(TS)] 💾 Диск после очистки: ${DISK_PCT_AFTER}%" >> "$LOG"
fi

# ── Проверяем наличие новых коммитов ─────────────────────────────────────────
git fetch origin main --quiet 2>> "$LOG"

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0   # нет изменений — тихо выходим
fi

SHORT_LOCAL="${LOCAL:0:7}"
SHORT_REMOTE="${REMOTE:0:7}"
echo "" >> "$LOG"
echo "═══════════════════════════════════════════════" >> "$LOG"
echo "[$(TS)] 🚀 ДЕПЛОЙ: $SHORT_LOCAL → $SHORT_REMOTE" >> "$LOG"

# ── Применяем новый код ───────────────────────────────────────────────────────
git reset --hard origin/main >> "$LOG" 2>&1
echo "[$(TS)] ✅ git reset OK" >> "$LOG"

# ── Собираем и запускаем ─────────────────────────────────────────────────────
docker compose up -d --build --remove-orphans --force-recreate >> "$LOG" 2>&1
echo "[$(TS)] ✅ docker compose OK" >> "$LOG"

# ── Health-check (ждём до 60 сек) ───────────────────────────────────────────
echo "[$(TS)] ⏳ Ждём старта (health-check)..." >> "$LOG"
for i in $(seq 1 12); do
    sleep 5
    if curl -sf http://localhost:5000/api/status > /dev/null 2>&1; then
        echo "[$(TS)] ✅ Health OK — бот запущен (попытка $i)" >> "$LOG"
        HEALTH_OK=1
        break
    fi
done

if [ "${HEALTH_OK:-0}" = "0" ]; then
    echo "[$(TS)] ⚠️  Health-check не прошёл за 60 сек — проверь логи: docker compose logs" >> "$LOG"
fi

# ── Telegram-уведомление ──────────────────────────────────────────────────────
TG_TOKEN=$(grep TELEGRAM_BOT_TOKEN "$BOT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d ' ')
TG_CHAT=$(grep TELEGRAM_CHAT_ID  "$BOT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d ' ')

if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then
    STATUS="${HEALTH_OK:-0}"
    EMOJI=$( [ "$STATUS" = "1" ] && echo "✅" || echo "⚠️" )
    MSG="$EMOJI GRINCH-GRAM обновлён%0A$SHORT_LOCAL → $SHORT_REMOTE%0A$(TS)"
    curl -sf "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
         -d "chat_id=$TG_CHAT&text=$MSG" > /dev/null 2>&1 || true
fi

echo "[$(TS)] 🏁 Деплой завершён" >> "$LOG"
echo "═══════════════════════════════════════════════" >> "$LOG"

# ── Еженедельная очистка Docker (воскресенье, 03:00–04:59) ───────────────────
DOW=$(date '+%u')
HOUR=$(date '+%H')
if [ "$DOW" = "7" ] && [ "$HOUR" -ge 3 ] && [ "$HOUR" -lt 5 ]; then
    PRUNE_FLAG="$BOT_DIR/.last_docker_prune"
    TODAY=$(date '+%Y-%m-%d')
    if [ "$(cat "$PRUNE_FLAG" 2>/dev/null)" != "$TODAY" ]; then
        echo "[$(TS)] 🧹 Еженедельная очистка Docker build cache..." >> "$LOG"
        docker builder prune -f  >> "$LOG" 2>&1
        docker image prune -f    >> "$LOG" 2>&1
        echo "$TODAY" > "$PRUNE_FLAG"
        echo "[$(TS)] ✅ Очистка завершена" >> "$LOG"
    fi
fi
