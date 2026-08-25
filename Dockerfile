# ═══════════════════════════════════════════════════════════════════════════════
# AI-Trading — Ultra-light Dockerfile (no heavy ML libs, no Rust)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install minimal system deps (no rust, no cmake)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN groupadd -r bot && \
    useradd -r -g bot -d /app -s /sbin/nologin bot && \
    chown -R bot:bot /app

COPY --chown=bot:bot . .

RUN mkdir -p /app/data /app/backups /app/logs && \
    chown -R bot:bot /app

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=3000

USER bot

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
