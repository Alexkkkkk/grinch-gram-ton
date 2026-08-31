"""Flask app factory — production-ready with security hardening."""

import logging
import os
import time

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

    # SECURITY: SECRET_KEY must be set in production
    secret_key = Config.SECRET_KEY
    if not secret_key:
        secret_key = os.urandom(32).hex()
        logger.warning("SECRET_KEY not set — using ephemeral key")
    app.config["SECRET_KEY"] = secret_key

    # SECURITY: Secure session cookies
    # The VPS currently exposes port 3000 directly over HTTP. Enable this
    # flag explicitly when the app is placed behind an HTTPS reverse proxy.
    app.config["SESSION_COOKIE_SECURE"] = os.getenv(
        "SESSION_COOKIE_SECURE", "false"
    ).lower() in {
        "1",
        "true",
        "yes",
    }
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 3600

    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    # Rate limiting
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address

        Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=["200 per minute", "1000 per hour"],
            storage_uri="memory://",
        )
        logger.info("Rate limiting enabled")
    except ImportError:
        logger.warning("flask-limiter not installed — rate limiting disabled")

    # Security middleware integration
    try:
        import security

        @app.before_request
        def security_before_request():
            result = security.check_request()
            if result is not None:
                return result

        logger.info("Security middleware enabled")
    except ImportError:
        logger.warning("security module not available")
    except Exception as e:
        logger.warning("Security middleware init error: %s", e)

    # Request timing + security headers
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
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        response.headers["Server"] = "nginx"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.errorhandler(404)
    def not_found(e):
        # Silently handle common 404s to reduce log noise
        silent_paths = {
            "/favicon.ico",
            "/robots.txt",
            "/manifest.json",
            "/apple-touch-icon.png",
        }
        if request.path in silent_paths:
            return "", 204
        logger.debug("404: %s %s", request.method, request.path)
        return jsonify({"error": "Not found", "path": request.path}), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("Internal error: %s", e)
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(429)
    def rate_limit(e):
        return jsonify({"error": "Rate limit exceeded"}), 429

    from web.routes.api import api_bp
    from web.routes.auth import auth_bp
    from web.routes.dashboard import dash_bp
    from web.routes.health import health_bp
    from web.routes.stubs import stubs_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(stubs_bp)

    # NOTE: Price feed is initialized in main.py to avoid double-fetch on startup
    # The initial price fetch happens there before SocketIO starts broadcasting.

    return app
