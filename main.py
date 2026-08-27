"""Entry point — AI-Trading v3.1 (production-ready)."""

import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

from flask_socketio import SocketIO

from core.price_feed_real import (
    get_candles_timeframe,
    get_current_price,
    get_price_change_24h,
    register_price_callback,
)
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


def _init_prefetch():
    """Start price prefetcher — call AFTER app is ready."""
    from price_feed import _start_price_prefetch

    _start_price_prefetch()


def _broadcast_price(price: float):
    """Broadcast price update to all connected clients."""
    if socketio:
        socketio.emit("price", {"price": price, "timestamp": time.time()})


def _broadcast_status():
    """Broadcast full status to all clients every 2 seconds."""
    while True:
        try:
            if socketio:
                price = get_current_price()
                change = get_price_change_24h()
                candles = get_candles_timeframe("15m", 200)
                socketio.emit(
                    "status",
                    {
                        "price": price,
                        "change_24h": change,
                        "candles": candles,
                        "timestamp": time.time(),
                    },
                )
        except Exception as e:
            logger.warning("Broadcast error: %s", e)
        time.sleep(2)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    workers = int(os.environ.get("WEB_CONCURRENCY", 1))
    use_gunicorn = os.environ.get("GUNICORN", "false").lower() == "true"

    logger.info(
        "AI-Trading v3.1 starting | port=%d workers=%d gunicorn=%s",
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

    # Register price callback for real-time updates
    register_price_callback(_broadcast_price)

    # Start background broadcaster
    _broadcast_thread = threading.Thread(target=_broadcast_status, daemon=True)
    _broadcast_thread.start()

    # Start background services AFTER SocketIO is ready
    _init_prefetch()

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
