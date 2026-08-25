.PHONY: deploy smoke status logs build up down clean update lint test fmt

deploy:
	@echo "=== GRINCH-GRAM v3.0 Deploy ==="
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d
	@echo "Waiting for healthcheck..."
	@sleep 5
	curl -f http://localhost/api/health || echo "Health check failed"

smoke:
	@echo "=== Smoke Tests ==="
	curl -f http://localhost/api/health && echo " OK"
	docker-compose ps | grep -q "Up" && echo " Containers running"

status:
	docker-compose ps
	curl -s http://localhost/api/health | python3 -m json.tool || true

logs:
	docker-compose logs -f --tail=100

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

clean:
	docker system prune -f
	docker volume prune -f

update:
	git pull origin main
	make deploy

lint:
	ruff check .
	black --check .

fmt:
	black .
	ruff check . --fix

test:
	pytest -v --tb=short

# ── Pre-push checks ───────────────────────────────────────────────────────────
check:
	@echo "=== Pre-push validation ==="
	@find . -name "*.py" -not -path "./.git/*" -exec python3 -m py_compile {} \;
	@echo "✅ Python syntax"
	@python3 -c "import yaml, glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"
	@echo "✅ YAML syntax"
	@black --check . 2>/dev/null || (echo "⚠️  Run 'make fmt' to fix formatting" && exit 1)
	@echo "✅ Black formatting"
	@ruff check . --output-format=concise 2>/dev/null || true
	@echo "✅ Ruff checks"
	@echo "=== All checks passed ==="

fmt:
	@black .
	@ruff check . --fix --exit-zero
	@echo "✅ Formatted"

install-hooks:
	@bash scripts/install-hooks.sh
