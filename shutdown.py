"""Graceful shutdown handler for SIGTERM/SIGINT."""

import logging
import signal
import sys
import threading
import time
from typing import Callable, List

logger = logging.getLogger("shutdown")

_handlers: List[Callable[[], None]] = []
_lock = threading.Lock()
_shutting_down = False


def register_handler(fn: Callable[[], None]):
    with _lock:
        _handlers.append(fn)


def _on_signal(signum, frame):
    global _shutting_down
    if _shutting_down:
        logger.warning("Forced exit — shutdown already in progress")
        sys.exit(1)
    _shutting_down = True
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — graceful shutdown (%d handlers)...", sig_name, len(_handlers))
    for handler in _handlers:
        try:
            handler()
        except Exception as exc:
            logger.error("Shutdown handler failed: %s", exc)
    logger.info("Graceful shutdown complete")
    sys.exit(0)


def install_handlers():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    logger.info("Graceful shutdown handlers installed")
