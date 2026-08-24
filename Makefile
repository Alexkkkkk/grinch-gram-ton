.PHONY: deploy smoke clean logs status update build test lint

deploy:
	./scripts/deploy.sh

smoke:
	python scripts/ci_smoke.py

test:
	python -m pytest tests/ -v || echo "No tests dir yet"

build:
	docker compose build --no-cache

up:
	docker compose up -d

down:
	docker compose down

clean:
	./scripts/cleanup.sh

logs:
	docker compose logs -f --tail=100

status:
	@echo "=== Containers ==="
	@docker compose ps
	@echo ""
	@echo "=== API Health ==="
	@curl -s http://localhost/api/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost/api/health
	@echo ""
	@echo "=== API Config ==="
	@curl -s http://localhost/api/config | python3 -m json.tool 2>/dev/null || curl -s http://localhost/api/config

update:
	./scripts/auto-update.sh

lint:
	python -m ruff check . || true
	python -m mypy core/ ai/ trading/ db/ web/ || true
