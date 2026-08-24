# GRINCH-GRAM v2.0

GRINCH/TON DeDust Spot Grid Trading Bot with AI advisor.

## Quick Start

```bash
# Clone
git clone https://github.com/Alexkkkkk/grinch-gram-ton.git /opt/bot
cd /opt/bot

# First deploy
make deploy

# Check status
make status

# View logs
make logs
```

## Safe Deploy (prevents all known issues)

```bash
./scripts/deploy.sh
```

This script handles:
- ✅ Lock file (no parallel builds)
- ✅ Disk space check & auto-cleanup
- ✅ Git reset --hard with nginx symlink restore
- ✅ Docker build with --no-cache
- ✅ Smoke test after deploy
- ✅ Old image cleanup

## Auto-Update (cron, replaces watchtower)

```bash
# Add to crontab
echo "*/10 * * * * /opt/bot/scripts/auto-update.sh" | crontab -
```

## Manual Cleanup (if disk is full)

```bash
make clean
# or
./scripts/cleanup.sh
```

## Architecture

```
core/    — Shared infrastructure (events, config, base components)
ai/      — ML engine (lazy-loaded sklearn/xgboost)
trading/ — Position management, DCA, risk control
db/      — Repository pattern for data access
web/     — Flask blueprints (API, auth, dashboard)
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your values.

## Key Changes in v2.0

- **Zero circular imports** via `core/events.py` event bus
- **Lazy ML loading** — sklearn loads only on first AI call
- **Unified Config** — dataclass-based with env override
- **Modular AI** — `ai_engine.py` (189KB) → `ai/` package (~200 lines)
- **Modular Trading** — `trader.py` (306KB) → `trading/` package
- **Flask Blueprints** — `app.py` (160KB) → `web/routes/`
- **Repository Pattern** — unified DB access via `db/repositories.py`
