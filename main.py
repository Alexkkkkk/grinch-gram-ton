"""Entry point — GRINCH-GRAM v2.1 (production-ready)."""

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
        "GRINCH-GRAM v2.1 starting | port=%d workers=%d gunicorn=%s",
        port,
        workers,
        use_gunicorn,
    )

    if use_gunicorn and workers > 1:
        # Production: gunicorn + eventlet
        from gunicorn.app.base import BaseApplication

        class GrinchApp(BaseApplication):
            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super().__init__()

            def load_config(self):
                for key, value in self.options.items():
                    if key in self.cfg.settings and value is not None:
                        self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        GrinchApp(
            app,
            {
                "bind": f"0.0.0.0:{port}",
                "workers": workers,
                "worker_class": "eventlet",
                "accesslog": "-",
                "errorlog": "-",
                "capture_output": True,
                "enable_stdio_inheritance": True,
            },
        ).run()
    else:
        # Development / single-worker
        socketio = SocketIO(app, cors_allowed_origins=os.getenv("CORS_ALLOWED_ORIGINS", "https://localhost").split(","), async_mode="threading")
        socketio.run(
            app,
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            # allow_unsafe_werkzeug removed — use gunicorn in production
        )

# SECURITY: explicit initialization instead of import-time side effects
from price_feed import PriceFeed
price_feed = PriceFeed()
price_feed.start()
