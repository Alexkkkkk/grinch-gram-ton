"""Small WSGI error boundary used outside Flask's own error handlers."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware:
    """Turn uncaught WSGI application exceptions into a JSON 500 response."""

    def __init__(self, application: Callable):
        self.application = application

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        try:
            return self.application(environ, start_response)
        except Exception:
            logger.exception("Unhandled exception in WSGI application")
            body = json.dumps(
                {"ok": False, "error": "Internal server error"}
            ).encode("utf-8")
            start_response(
                "500 Internal Server Error",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]