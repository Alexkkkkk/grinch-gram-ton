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
