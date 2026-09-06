"""Entry point — AI-Trading v3.2 (synchronized & optimized)."""

import hashlib
import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Dict

from flask import request
from flask_socketio import SocketIO

from core.price_feed_real import (
    get_candles_timeframe,
    get_current_price,
    get_feed_status,
    get_price_change_24h,
    register_price_callback,
    start_background_updates,
    tick_price,
    update_price,
)
from dedust_client import dedust_client
from grid_trader import GridTrader
from quantum_brain import get_brain
from quantum_evolution import get_evolution
from web.app import create_app
from web.routes.api import set_brain as api_set_brain
from web.routes.api import set_grid_trader

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("grinch")

app = create_app()

# Initialize SocketIO — pure threading (no eventlet to avoid blocking errors)
socketio = SocketIO(
    app,
    cors_allowed_origins=os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "https://localhost,http://localhost,http://2.27.25.126:3000,https://2.27.25.126:3000",
    ).split(","),
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Unified Component Initialization (order matters)
# ═══════════════════════════════════════════════════════════════════════════════

# 1. Quantum Brain (unified AI)
brain = get_brain()

# 2. GridTrader
grid_trader = GridTrader()
grid_trader.inject(
    dedust_client=dedust_client, ai_engine=brain, price_feed=get_current_price
)
grid_trader.start_poller()

# 3. Connect brain to grid trader and price feed
brain.inject(grid_trader=grid_trader, price_feed=get_current_price)
brain.start()

# 4. Register with API (synchronized)
set_grid_trader(grid_trader)
api_set_brain(brain)

# 5. Evolution Engine
evo = get_evolution()
logger.info("[QuantumEvolution] Engine initialized with population size 20")

logger.info("[QuantumBrain] Unified AI system initialized")


# ═══════════════════════════════════════════════════════════════════════════════
# Graceful Shutdown
# ═══════════════════════════════════════════════════════════════════════════════

_shutdown_event = threading.Event()


def _graceful_shutdown(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    logger.info("Received signal %s, shutting down gracefully...", signum)
    _shutdown_event.set()
    grid_trader.stop()
    brain.stop()
    if socketio:
        try:
            socketio.stop()
        except RuntimeError:
            # Gunicorn may invoke the signal handler outside an HTTP request;
            # Flask-SocketIO cannot stop its Werkzeug server in that context.
            logger.debug("SocketIO stop skipped outside request context")
    sys.exit(0)


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


# ═══════════════════════════════════════════════════════════════════════════════
# Price Prefetch
# ═══════════════════════════════════════════════════════════════════════════════


def _init_prefetch():
    """Start price prefetcher."""
    from price_feed import _start_price_prefetch

    _start_price_prefetch()


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Broadcasting (thread-safe, optimized)
# ═══════════════════════════════════════════════════════════════════════════════

_last_candle_hashes: Dict[str, str] = {}
_candle_hash_lock = threading.Lock()
_client_timeframes: Dict[str, str] = {}
_tf_lock = threading.Lock()


def _broadcast_price(price: float):
    """Broadcast price update to all connected clients."""
    if socketio and not _shutdown_event.is_set():
        feed = get_feed_status()
        socketio.emit(
            "price",
            {
                "price": price,
                "timestamp": time.time(),
                "source": feed.get("source"),
                "stale": feed.get("stale", True),
                "available": feed.get("available", False),
            },
        )


def _broadcast_status():
    """Broadcast status + candles to all clients every 2 seconds."""
    last_candle_send = 0

    while not _shutdown_event.is_set():
        try:
            if socketio:
                price = get_current_price()
                tick_price(price)
                change = get_price_change_24h()
                feed = get_feed_status()

                # Lightweight status every 2s
                socketio.emit(
                    "status",
                    {
                        "price": price,
                        "change_24h": change,
                        "timestamp": time.time(),
                        "source": feed.get("source"),
                        "stale": feed.get("stale", True),
                        "available": feed.get("available", False),
                        "error": feed.get("error"),
                    },
                )

                # Candles: send every 3s and independently to each client's
                # selected timeframe. A single global timeframe caused one
                # client's selection to overwrite another's chart.
                now = time.time()
                if now - last_candle_send >= 3:
                    with _tf_lock:
                        clients_by_tf: Dict[str, list[str]] = {}
                        for sid, timeframe in _client_timeframes.items():
                            clients_by_tf.setdefault(timeframe, []).append(sid)

                    for timeframe, sids in clients_by_tf.items():
                        candles = get_candles_timeframe(timeframe, 300)
                        candle_json = json.dumps(
                            candles, sort_keys=True, separators=(",", ":")
                        )
                        candle_hash = hashlib.md5(
                            candle_json.encode(), usedforsecurity=False
                        ).hexdigest()

                        with _candle_hash_lock:
                            send_it = candle_hash != _last_candle_hashes.get(timeframe)
                            if send_it:
                                _last_candle_hashes[timeframe] = candle_hash

                        if send_it:
                            payload = {
                                "candles": candles,
                                "timeframe": timeframe,
                                "timestamp": now,
                            }
                            for sid in sids:
                                socketio.emit("candles", payload, to=sid)
                    last_candle_send = now
        except Exception as e:
            logger.warning("Broadcast error: %s", e)
        _shutdown_event.wait(2)


@socketio.on("subscribe_timeframe")
def _handle_subscribe_timeframe(data):
    """Client tells us which timeframe it's viewing."""
    try:
        sid = request.sid
    except RuntimeError:
        sid = None
    if sid and data and data.get("timeframe"):
        timeframe = str(data["timeframe"])
        with _tf_lock:
            _client_timeframes[sid] = timeframe
        # Send the selected timeframe immediately so a newly connected client
        # does not wait for the next broadcaster tick or another price change.
        candles = get_candles_timeframe(timeframe, 300)
        socketio.emit(
            "candles",
            {
                "candles": candles,
                "timeframe": timeframe,
                "timestamp": time.time(),
            },
            to=sid,
        )


@socketio.on("disconnect")
def _handle_disconnect():
    """Clean up client timeframe tracking."""
    try:
        sid = request.sid
    except RuntimeError:
        sid = None
    if sid:
        with _tf_lock:
            _client_timeframes.pop(sid, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Startup Sequence
# ═══════════════════════════════════════════════════════════════════════════════

# Fetch initial price immediately
try:
    update_price()
    logger.info("[PriceFeed] Initial price fetched: $%.4f", get_current_price())
except Exception as e:
    logger.warning("[PriceFeed] Initial price fetch failed: %s", e)

# Register price callback for real-time updates
register_price_callback(_broadcast_price)

# Start background broadcaster
_broadcast_thread = threading.Thread(target=_broadcast_status, daemon=True)
_broadcast_thread.start()

# Start background price feed from exchanges
start_background_updates(interval=3.0)

# Start background services
_init_prefetch()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    workers = int(os.environ.get("WEB_CONCURRENCY", 1))
    use_gunicorn = os.environ.get("GUNICORN", "false").lower() == "true"

    logger.info(
        "AI-Trading v3.2 starting | port=%d workers=%d gunicorn=%s",
        port,
        workers,
        use_gunicorn,
    )

    if use_gunicorn and workers > 1:
        logger.warning(
            "Gunicorn with multiple workers requested but this path is deprecated. "
            "Use 'gunicorn -c gunicorn.conf.py main:app' instead."
        )

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
