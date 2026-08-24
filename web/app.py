"""Flask app factory — production-ready."""

import logging
import os
import time
from typing import Any

from flask import Flask, jsonify, request

from core.base_components import NpEncoder
from core.config import Config

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )
    app.json_encoder = NpEncoder
    app.config["SECRET_KEY"] = Config.SECRET_KEY or os.urandom(32).hex()
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

    # Request timing middleware
    @app.before_request
    def before_request():
        request._start_time = time.time()

    @app.after_request
    def after_request(response):
        duration = (time.time() - getattr(request, "_start_time", time.time())) * 1000
        logger.info(
            "%s %s %s %.2fms",
            request.method,
            request.path,
            response.status_code,
            duration,
        )
        response.headers["X-Response-Time"] = f"{duration:.2f}ms"
        return response

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found", "path": request.path}), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("Internal error: %s", e)
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(429)
    def rate_limit(e):
        return jsonify({"error": "Rate limit exceeded"}), 429

    # Health check (before blueprints)
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "version": "2.1.0"})

    # Register blueprints
    from web.routes.api import api_bp
    from web.routes.auth import auth_bp
    from web.routes.dashboard import dash_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)

    return app
