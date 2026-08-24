"""Request timing middleware."""

import time
import logging

logger = logging.getLogger(__name__)


class TimingMiddleware:
    """Add X-Response-Time header and log request duration."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        start = time.time()

        def custom_start_response(status, headers, exc_info=None):
            duration = (time.time() - start) * 1000
            headers.append(("X-Response-Time", f"{duration:.2f}ms"))
            logger.info(
                "%s %s | %.2fms",
                environ.get("REQUEST_METHOD"),
                environ.get("PATH_INFO"),
                duration,
            )
            return start_response(status, headers, exc_info)

        return self.app(environ, custom_start_response)
