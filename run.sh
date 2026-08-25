#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# GRINCH-GRAM → GRINCH/GRAM (DeDust) — Запуск
# ═══════════════════════════════════════════════════════════════════════════════
set -e

cd "$(dirname "$0")"

echo "=========================================="
echo "   GRINCH-GRAM  →  GRINCH/GRAM (DeDust)"
echo "=========================================="

# Проверка .env
if [ ! -f ".env" ]; then
    echo "[!] .env не найден. Копируем из .env.example..."
    cp .env.example .env
    echo "⚠️  Отредактируйте .env и укажите TON_MNEMONIC!"
    exit 1
fi

# Проверка мнемоники
MNEMONIC=$(grep "^TON_MNEMONIC=" .env | cut -d'=' -f2- | head -1 | tr -d ' ')
if [ -z "$MNEMONIC" ] || echo "$MNEMONIC" | grep -q "abandon"; then
    echo "⚠️  TON_MNEMONIC не настроен!"
    echo "   Отредактируйте .env и укажите реальную мнемонику."
    exit 1
fi

echo "🚀 Запуск..."
python3 app.py
