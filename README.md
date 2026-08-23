# GRINCH-GRAM → GRINCH/GRAM (GRINCH/TON) Spot Grid на DeDust

Автоматизированный Spot Grid бот для торговли парой **GRINCH/GRAM (GRINCH/TON)** на децентрализованной бирже [DeDust](https://dedust.io).

## ⚡ Быстрый старт

```bash
# 1. Установка зависимостей
pip install -r requirements.txt

# 2. Настройка окружения
cp .env.example .env
nano .env  # ← замените TON_MNEMONIC на реальные 24 слова

# 3. Запуск
python app.py
```

Дашборд: http://localhost:5000

## 📊 Параметры сетки

| Параметр | Значение |
|----------|----------|
| Пул | [GRINCH/TON](https://dedust.io/pools/EQDpVwTQr53cwgaT_VCFsmrleg5fBvStTjMrvyvprF_ROC9Z) |
| Комиссия DEX | 1.0% за сторону |
| Шаг сетки | 3.5% |
| Уровней | 40 (20 buy + 20 sell) |
| Чистая прибыль/сетка | ~1.45% |
| Диапазон | ±50% от центральной цены |

## 🔧 Настройка TON-кошелька

1. Установите **TonKeeper** или **mytonwallet**
2. Создайте/импортируйте кошелёк
3. Пополните баланс:
   - **TON** — для газа и покупок (~50–500 TON)
   - **GRINCH** — для продаж
4. Получите **24 слова мнемоники** (Settings → Recovery Phrase)
5. Вставьте в `.env`

## 🛡️ Безопасность

- **Никогда** не публикуйте `TON_MNEMONIC`
- Первый запуск с `DEMO_MODE=true`
- Минимальный резерв газа: **0.45 TON**

## 🔗 Ссылки

- Токен GRINCH: https://dedust.io/coins/EQA6G0uVERDZTkLNa0drWBna1F5TSbogy7UXEWU5ERHz4uJL
- Пул GRINCH/TON: https://dedust.io/pools/EQDpVwTQr53cwgaT_VCFsmrleg5fBvStTjMrvyvprF_ROC9Z
