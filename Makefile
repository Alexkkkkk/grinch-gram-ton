.PHONY: up down up-prod down-prod logs build build-prod clean clean-all test

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# ═══════════════════════════════════════════════════════════════════════════════
# Standalone (single container, SQLite)
# ═══════════════════════════════════════════════════════════════════════════════

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f bot --tail 50

build:
	docker-compose build --parallel --progress=plain bot

# ═══════════════════════════════════════════════════════════════════════════════
# Production (PostgreSQL + Redis + Bot + Nginx)
# ═══════════════════════════════════════════════════════════════════════════════

up-prod:
	docker-compose -f docker-compose.prod.yml up -d

down-prod:
	docker-compose -f docker-compose.prod.yml down

logs-prod:
	docker-compose -f docker-compose.prod.yml logs -f bot --tail 50

build-prod:
	docker-compose -f docker-compose.prod.yml build --parallel --progress=plain bot

# ═══════════════════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════════════════

test:
	python -m pytest tests/ -v --tb=short

clean:
	docker system prune -f

clean-all:
	docker-compose -f docker-compose.prod.yml down -v
	docker system prune -af

shell:
	docker-compose exec bot bash

migrate:
	docker-compose exec bot python -c "from web.app import create_app; from models import db; app = create_app(); app.app_context().push(); db.create_all(); print('OK')"
