"""Flask app factory — replaces monolithic app.py."""
import logging
import os

from flask import Flask

from core.base_components import NpEncoder
from core.config import Config

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    app.json_encoder = NpEncoder
    app.config["SECRET_KEY"] = Config.SECRET_KEY or os.urandom(32).hex()
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600

    # Register blueprints
    from web.routes.api import api_bp
    from web.routes.auth import auth_bp
    from web.routes.dashboard import dash_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)

    return app
