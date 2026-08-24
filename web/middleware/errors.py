"""Error handling middleware — JSON error responses."""

import logging
import traceback
from flask import jsonify

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware:
    """Convert exceptions to JSON error responses."""

    @staticmethod
    def register(app):
        @app.errorhandler(404)
        def not_found(e):
            return (
                jsonify({"error": "Not found", "path": getattr(e, "path", None)}),
                404,
            )

        @app.errorhandler(500)
        def internal_error(e):
            logger.exception("Internal server error")
            return jsonify({"error": "Internal server error", "detail": str(e)}), 500

        @app.errorhandler(429)
        def rate_limit(e):
            return (
                jsonify(
                    {
                        "error": "Rate limit exceeded",
                        "retry_after": getattr(e, "retry_after", 60),
                    }
                ),
                429,
            )

        @app.errorhandler(400)
        def bad_request(e):
            return jsonify({"error": "Bad request", "detail": str(e)}), 400
