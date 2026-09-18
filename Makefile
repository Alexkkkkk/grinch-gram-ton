.PHONY: up down up-prod down-prod logs build build-prod clean clean-all test

PROD_COMPOSE := docker-compose.prod.yml

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

# Fails fast with a clear message instead of a confusing compose error
check-prod:
	@test -f $(PROD_COMPOSE) || { echo "ERROR: $(PROD_COMPOSE) is missing. Use 'make up' (single-container) or add the prod compose file."; exit 1; }

up-prod: check-prod
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
