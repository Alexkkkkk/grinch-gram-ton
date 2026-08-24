# GRINCH-GRAM v3.0

GRINCH/TON DeDust Spot Grid Trading Bot with AI advisor.

## Quick Start

```bash
git clone https://github.com/Alexkkkkk/grinch-gram-ton.git /opt/bot
cd /opt/bot
cp .env.example .env
# Edit .env with your settings
make deploy
```

## Architecture v3.0

```
core/          — Shared infrastructure (events, config, base components)
  config.py    — Legacy dataclass config (backward compat)
  config_v2.py — Pydantic config with validation (new, opt-in)
ai/            — ML engine (lazy-loaded sklearn/xgboost)
trading/       — Position management, DCA, risk control
  engine/      — Position, Grid, DCA, Scalp engines
  risk/        — Stop-loss, trailing, circuit breaker, sizing
  analysis/    — Signals, trends, confluence
db/            — Repository pattern for data access
web/           — Flask blueprints (API, auth, dashboard)
  middleware/  — Timing, auth, errors, rate limiting
```

## Commands

| Command | Description |
|---------|-------------|
| `make deploy` | Safe deploy with health checks |
| `make smoke` | Run CI smoke tests |
| `make status` | Check containers + API health |
| `make logs` | Tail container logs |
| `make build` | Rebuild Docker images |
| `make up` | Start containers |
| `make down` | Stop containers |
| `make clean` | Disk cleanup |
| `make update` | Pull latest + deploy |
| `make lint` | Run ruff + black check |
| `make fmt` | Auto-format code |
| `make test` | Run pytest |

## Auto-Update

```bash
echo "*/10 * * * * /opt/bot/scripts/auto-update.sh" | crontab -
```

## Environment

Copy `.env.example` to `.env` and fill in your values.

## Key Features v3.0

- **Zero circular imports** via `core/events.py`
- **Lazy ML loading** — sklearn loads only on first AI call
- **Unified Config** — dataclass-based with env override (legacy) + Pydantic v2 (new)
- **Memory optimized** — `__slots__` on hot-path classes
- **Graceful shutdown** — SIGTERM/SIGINT handling
- **Health checks** — Docker + nginx + Flask
- **Rate limiting** — nginx + auth blueprint
- **Gzip compression** — nginx
- **Log rotation** — Docker json-file driver
- **Resource limits** — CPU/memory caps in compose
- **Modular trading** — Position/Grid/DCA/Scalp engines
- **Risk management** — Multi-stage trailing, circuit breaker, position sizing
- **CI/CD** — GitHub Actions with lint, test, security scan

## Migration from v2.1

v3.0 removes duplicate root modules. If you imported `config`, `app`, or `trader` directly from root, update to:

```python
from core.config import Config      # was: import config
from web.app import create_app       # was: import app
from trading.trader import Trader    # was: import trader
```

## License

MIT
