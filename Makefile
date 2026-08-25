.PHONY: up down up-prod down-prod logs build clean

# ── Standalone (single container, SQLite) ────────────────────────────────────
up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f bot --tail 50

# ── Production (PostgreSQL + Redis + Nginx) ─────────────────────────────────
up-prod:
	docker-compose -f docker-compose.prod.yml up -d

down-prod:
	docker-compose -f docker-compose.prod.yml down

logs-prod:
	docker-compose -f docker-compose.prod.yml logs -f bot --tail 50

# ── Build ────────────────────────────────────────────────────────────────────
build:
	docker-compose build --no-cache bot

build-prod:
	docker-compose -f docker-compose.prod.yml build --no-cache bot

# ── Clean ────────────────────────────────────────────────────────────────────
clean:
	docker system prune -f

clean-all:
	docker-compose -f docker-compose.prod.yml down -v
	docker system prune -af
