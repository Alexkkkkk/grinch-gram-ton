# ═══════════════════════════════════════════════════════════════════════════════
# AI-Trading — Ultra-light multi-stage Dockerfile
# Target: ~400-600 MB (was 6.8 GB due to .git/ + data/ + no .dockerignore)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r bot && useradd -r -g bot -d /app -s /sbin/nologin bot

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only source code — no .git/, data/, logs/ (see .dockerignore)
COPY --chown=bot:bot *.py pyproject.toml ./
COPY --chown=bot:bot core/ ./core/
COPY --chown=bot:bot web/ ./web/
COPY --chown=bot:bot trading/ ./trading/
COPY --chown=bot:bot ai/ ./ai/
COPY --chown=bot:bot db/ ./db/
COPY --chown=bot:bot autonomy/ ./autonomy/
COPY --chown=bot:bot scripts/ ./scripts/
COPY --chown=bot:bot static/ ./static/
COPY --chown=bot:bot templates/ ./templates/

RUN mkdir -p /app/data /app/backups /app/logs && chown -R bot:bot /app

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=3000

USER bot

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
