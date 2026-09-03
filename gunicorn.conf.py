"""Gunicorn configuration — threading-compatible (no eventlet)."""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"

# Socket.IO runs in threading mode — use gthread worker (built-in, no eventlet)
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
# Background pollers must share state with the HTTP worker.
preload_app = False
# Worker recycling used to reset the displayed uptime every ~500 requests
# and could hang because the app owns long-lived background threads. Keep it
# opt-in so uptime is stable; operators can set a bounded value explicitly.
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "0"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "0"))

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190
