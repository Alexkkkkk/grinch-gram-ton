"""Gunicorn configuration — optimized for 2 GB RAM VPS."""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"

# ═══════════════════════════════════════════════════════════════════════════════
# RAM-OPTIMIZED: 2 GB VPS → 1 worker + 4 threads (thread-based concurrency)
# ═══════════════════════════════════════════════════════════════════════════════
# Why 1 worker?
#   - Each worker = separate Python process with its own copy of loaded modules.
#   - With sklearn + numpy + pandas imported, each worker eats ~300-500 MB.
#   - 5 workers (default formula) = 1.5-2.5 GB just for gunicorn → OOM kills.
# Why threads?
#   - "gthread" handles concurrent requests inside ONE process via threads.
#   - Threads share memory → no duplication of AI models / numpy arrays.
#   - 4 threads is enough for a trading bot dashboard (mostly long-polling).
# ═══════════════════════════════════════════════════════════════════════════════
workers = int(os.getenv("WEB_CONCURRENCY", 1))
threads = int(os.getenv("GUNICORN_THREADS", 4))
worker_class = "gthread"
worker_connections = 1000

# Timeouts
timeout = 30
keepalive = 5
graceful_timeout = 10

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
capture_output = True
enable_stdio_inheritance = True

# Performance
preload_app = True
max_requests = 500
max_requests_jitter = 50

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190
