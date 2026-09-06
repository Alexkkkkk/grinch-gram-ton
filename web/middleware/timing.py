"""Request timing middleware.

The Flask app records request timings itself, but this small WSGI wrapper is
also useful for deployments that wrap the app before Flask is created.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable


class TimingMiddleware:
    """Add an ``X-Response-Time`` header to every WSGI response."""

    def __init__(self, application: Callable):
        self.application = application

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        started = time.perf_counter()

        def timed_start_response(status, headers, exc_info=None):
            elapsed_ms = (time.perf_counter() - started) * 1000
            response_headers = list(headers)
            response_headers.append(("X-Response-Time", f"{elapsed_ms:.2f}ms"))
            return start_response(status, response_headers, exc_info)

        return self.application(environ, timed_start_response)
