"""Entry point — GRINCH-GRAM v2.0."""
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from web.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    logger.info("GRINCH-GRAM v2.0 starting on port %d", port)
    from flask_socketio import SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
