# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-08-24

### Added
- Modular trading architecture with `trading/engine/`, `trading/risk/`, `trading/analysis/`
- Pydantic-based configuration (`core/config_v2.py`) with validation and SecretStr
- Web middleware (`web/middleware/`) for timing and error handling
- Production Dockerfile with multi-stage build and non-root user
- Gunicorn configuration with auto workers and health checks
- GitHub Actions CI/CD pipeline (lint, test, security, coverage)
- Docker Compose with resource limits and depends_on conditions
- Pre-commit hooks (black, ruff, mypy, trailing-whitespace)
- Dependabot configuration for pip and docker
- CODEOWNERS file

### Changed
- Updated README with v3.0 architecture and migration guide
- Enhanced `.gitignore` for complete v3.0 workflow
- Updated Makefile with `lint`, `fmt`, `test` commands

### Removed
- Duplicate root modules: `app.py`, `config.py`, `trader.py`
- Legacy AI modules: `ai_engine.py`, `ai_backend.py`, `ai_entry_optimizer.py`, `ai_tp_optimizer.py`, `ai_market_scanner.py`
- Legacy DB modules: `grid_db.py`, `fix_grid_ids.py`

### Fixed
- Migrated all `from config import` to `from core.config import` in 12 files
- Package `__init__.py` exports updated for proper imports

## [2.1.0] - 2024

### Added
- Zero circular imports via `core/events.py`
- Lazy ML loading
- Unified Config with env override
- Memory optimized `__slots__`
- Graceful shutdown handling
- Health checks, rate limiting, gzip compression

### Fixed
- Various bug fixes and performance improvements
