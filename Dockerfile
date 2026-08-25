# ═══════════════════════════════════════════════════════════════════════════════
# GRINCH-GRAM v3.1 — Production Dockerfile
# ═══════════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd -r grinch && \
    useradd -r -g grinch -d /app -s /sbin/nologin grinch && \
    chown -R grinch:grinch /app

# Copy application code
COPY --chown=grinch:grinch . .

# Create data directories
RUN mkdir -p /app/data /app/backups /app/logs && \
    chown -R grinch:grinch /app

# Environment
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=3000

USER grinch

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
