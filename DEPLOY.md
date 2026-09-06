# Деплой QuantumGrinch v7 на VPS

## 1. Подключиться к серверу

```bash
ssh root@2.27.25.126
```

---

## 2. Установить Docker и Git

```bash
apt-get update && apt-get install -y git docker.io docker-compose
systemctl enable docker && systemctl start docker
```

---

## 3. Склонировать репозиторий

```bash
git clone https://github.com/Alexkkkkk/grinch-gram-ton.git /opt/bot
cd /opt/bot
```

---

## 4. Создать .env с секретами

```bash
cp .env.example .env
nano .env
```

**Обязательно заполни:**
```env
TON_MNEMONIC=your 24 words here
TON_WALLET=EQ...your_address...
TONCENTER_API_KEY=your_toncenter_key
ADMIN_PASSWORD=strong_password
SECRET_KEY=random_64_char_string
```

Сохранить: `Ctrl+O` → `Enter` → `Ctrl+X`

---

## 5. Запустить бота

```bash
cd /opt/bot
docker-compose up -d --build
```

Первый запуск: ~5–10 минут (скачивает Python-пакеты).

---

## 6. Проверить что работает

```bash
# Логи в реальном времени
docker-compose logs -f

# Статус контейнера
docker-compose ps

# Health check
curl http://localhost:3000/api/health
```

---

## 7. Открыть дашборд

```
http://2.27.25.126:3000
```

Логин: `admin`  
Пароль: тот что в `ADMIN_PASSWORD`

---

## Полезные команды

```bash
# Перезапуск
sudo docker-compose restart

# Остановить
sudo docker-compose down

# Обновить код и перезапустить
cd /opt/bot && git pull && sudo docker-compose up -d --build

# Посмотреть RAM
docker stats

# Бэкап данных
tar czf backup-$(date +%Y%m%d).tar.gz data/ backups/ logs/
```

---

## Обновление без Git (если менял код локально)

```bash
cd /opt/bot
git stash && git pull && git stash pop
sudo docker-compose up -d --build
```
