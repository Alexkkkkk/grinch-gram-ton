#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Push GRINCH-GRAM-TON на GitHub
# ═══════════════════════════════════════════════════════════════════════════════
set -e

REPO_NAME="grinch-gram-ton"

echo "=========================================="
echo "   Push GRINCH-GRAM-TON → GitHub"
echo "=========================================="

# Проверка git
if ! command -v git &> /dev/null; then
    echo "❌ git не установлен"
    exit 1
fi

# Проверка curl
if ! command -v curl &> /dev/null; then
    echo "❌ curl не установлен"
    exit 1
fi

# Запрос токена
echo ""
echo "📋 Создайте новый токен:"
echo "   https://github.com/settings/tokens/new"
echo "   → Выберите 'repo' (полный доступ)"
echo "   → Generate token"
echo ""
read -s -p "🔑 Введите GitHub Personal Access Token: " GITHUB_TOKEN
echo ""

if [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ Токен не введён"
    exit 1
fi

# Проверка токена
echo "🔍 Проверка токена..."
USER=$(curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | grep -o '"login":"[^"]*"' | cut -d'"' -f4)

if [ -z "$USER" ]; then
    echo "❌ Неверный токен или нет доступа к API"
    exit 1
fi

echo "✅ Авторизован как: $USER"

# Создание репозитория
echo "📦 Создание репозитория $REPO_NAME..."
RESPONSE=$(curl -s -X POST \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    https://api.github.com/user/repos \
    -d "{\"name\":\"$REPO_NAME\",\"private\":false,\"description\":\"GRINCH-GRAM → GRINCH/GRAM (GRINCH/TON) Spot Grid на DeDust\"}")

if echo "$RESPONSE" | grep -q "already exists"; then
    echo "⚠️  Репозиторий уже существует"
    read -p "   Перезаписать? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
elif echo "$RESPONSE" | grep -q '"id"'; then
    echo "✅ Репозиторий создан: https://github.com/$USER/$REPO_NAME"
else
    echo "❌ Ошибка создания репозитория:"
    echo "$RESPONSE"
    exit 1
fi

# Git config
cd "$(dirname "$0")"

if [ ! -d ".git" ]; then
    echo "🔧 Инициализация git..."
    git init
    git branch -m main
fi

git config user.email "bot@grinch-gram.local" 2>/dev/null || true
git config user.name "GRINCH Bot" 2>/dev/null || true

# Commit
echo "💾 Commit..."
git add -A
git commit -m "GRINCH-GRAM → GRINCH/GRAM (GRINCH/TON) Spot Grid на DeDust

- Заточка под пул GRINCH/TON на DeDust
- 40 уровней сетки (20 buy + 20 sell)
- Шаг 3.5% (покрывает 1% комиссию DEX)
- Адреса контрактов: GRINCH/TON
- AI отключён для чистой Spot Grid
- Добавлен .env.example и run.sh" 2>/dev/null || echo "(нет изменений для коммита)"

# Push
echo "🚀 Push на GitHub..."
git remote remove origin 2>/dev/null || true
git remote add origin "https://$GITHUB_TOKEN@github.com/$USER/$REPO_NAME.git"
git push -u origin main --force

echo ""
echo "=========================================="
echo "✅ ГОТОВО!"
echo "=========================================="
echo ""
echo "📎 Репозиторий: https://github.com/$USER/$REPO_NAME"
echo ""
echo "⚠️  ВАЖНО: Удалите токен после использования:"
echo "   https://github.com/settings/tokens"
echo ""
