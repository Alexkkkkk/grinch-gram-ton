.PHONY: deploy smoke clean logs status

deploy:
	./scripts/deploy.sh

smoke:
	docker compose exec bot python scripts/ci_smoke.py

clean:
	./scripts/cleanup.sh

logs:
	docker compose logs -f --tail=100

status:
	docker compose ps
	@echo "---"
	@curl -s http://localhost/api/config | python3 -m json.tool 2>/dev/null || curl -s http://localhost/api/config

update:
	./scripts/auto-update.sh
