"""Entry point — AI-Trading v2.1 (production-ready)."""

import logging
import os
import signal
import sys
from typing import Optional

from flask_socketio import SocketIO

from web.app import create_app

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("grinch")

app = create_app()
socketio: Optional[SocketIO] = None


def _graceful_shutdown(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    logger.info("Received signal %s, shutting down gracefully...", signum)
    if socketio:
        socketio.stop()
    sys.exit(0)


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    workers = int(os.environ.get("WEB_CONCURRENCY", 1))
    use_gunicorn = os.environ.get("GUNICORN", "false").lower() == "true"

    logger.info(
        "AI-Trading v2.1 starting | port=%d workers=%d gunicorn=%s",
        port,
        workers,
        use_gunicorn,
    )

    if use_gunicorn and workers > 1:
        logger.warning(
            "Gunicorn with multiple workers requested but this path is deprecated. "
            "Use 'gunicorn -c gunicorn.conf.py main:app' instead."
        )

    # Development / single-worker (also used when gunicorn.conf.py handles workers)
    socketio = SocketIO(
        app,
        cors_allowed_origins=os.getenv(
            "CORS_ALLOWED_ORIGINS", "https://localhost"
        ).split(","),
        async_mode="threading",
    )
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        # allow_unsafe_werkzeug removed — use gunicorn in production
    )

# SECURITY: explicit initialization instead of import-time side effects
from price_feed import _start_price_prefetch  # noqa: E402

_start_price_prefetch()
