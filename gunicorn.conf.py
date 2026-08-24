"""Gunicorn configuration — production-optimized."""

import os
import multiprocessing

bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
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
max_requests = 1000
max_requests_jitter = 50

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190
