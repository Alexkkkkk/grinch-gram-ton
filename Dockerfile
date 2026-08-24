# ═══════════════════════════════════════════════════════════════════════════════
# GRINCH-GRAM v3.1 — Multi-stage Production Dockerfile
# ═══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r grinch && useradd -r -g grinch -d /app -s /sbin/nologin grinch

# Copy Python packages from builder
COPY --from=builder /root/.local /home/grinch/.local
RUN chown -R grinch:grinch /home/grinch/.local

# Set environment
ENV PATH=/home/grinch/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=3000

# Copy application code
COPY --chown=grinch:grinch . .

# Create data directories
RUN mkdir -p /app/data /app/backups /app/logs \
    && chown -R grinch:grinch /app

# Switch to non-root user
USER grinch

EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || exit 1

# Production: gunicorn with gevent worker (eventlet conflicts with asyncio)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
