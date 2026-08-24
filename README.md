# GRINCH-GRAM v2.1

GRINCH/TON DeDust Spot Grid Trading Bot with AI advisor.

## Quick Start

```bash
git clone https://github.com/Alexkkkkk/grinch-gram-ton.git /opt/bot
cd /opt/bot
make deploy
```

## Architecture

```
core/    — Shared infrastructure (events, config, base components)
ai/      — ML engine (lazy-loaded sklearn/xgboost)
trading/ — Position management, DCA, risk control
db/      — Repository pattern for data access
web/     — Flask blueprints (API, auth, dashboard)
```

## Commands

| Command | Description |
|---------|-------------|
| `make deploy` | Safe deploy with checks |
| `make smoke` | Run CI smoke tests |
| `make status` | Check containers + API |
| `make logs` | Tail container logs |
| `make build` | Rebuild Docker images |
| `make up` | Start containers |
| `make down` | Stop containers |
| `make clean` | Disk cleanup |
| `make update` | Manual update check |

## Auto-Update

```bash
echo "*/10 * * * * /opt/bot/scripts/auto-update.sh" | crontab -
```

## Environment

Copy `.env.example` to `.env` and fill in your values.

## Key Features v2.1

- **Zero circular imports** via `core/events.py`
- **Lazy ML loading** — sklearn loads only on first AI call
- **Unified Config** — dataclass-based with env override
- **Memory optimized** — `__slots__` on hot-path classes
- **Graceful shutdown** — SIGTERM/SIGINT handling
- **Health checks** — Docker + nginx + Flask
- **Rate limiting** — nginx + auth blueprint
- **Gzip compression** — nginx
- **Log rotation** — Docker json-file driver
- **Resource limits** — CPU/memory caps in compose
