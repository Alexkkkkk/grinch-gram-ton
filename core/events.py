"""Central event bus — zero circular imports, typed, weakref-safe."""

import threading
import weakref
from collections.abc import Callable
from typing import Any

# Use weakref for auto-cleanup of dead subscribers
_subscribers: dict[str, list[weakref.ref]] = {}
_lock = threading.RLock()

# Event constants
EVENT_AI_SIGNAL = "ai.signal"
EVENT_TRADE_CLOSED = "trade.closed"
EVENT_FUSION_UPDATE = "fusion.update"
EVENT_TRADE_OPENED = "trade.opened"
EVENT_CONFIG_CHANGED = "config.changed"
EVENT_PRICE_UPDATE = "price.update"


def subscribe(event: str, callback: Callable[[Any], None]) -> None:
    """Subscribe to an event. Thread-safe. Auto-cleans dead refs."""
    with _lock:
        refs = _subscribers.setdefault(event, [])
        # Clean dead refs
        refs[:] = [r for r in refs if r() is not None]
        refs.append(weakref.ref(callback))


def unsubscribe(event: str, callback: Callable[[Any], None]) -> None:
    """Unsubscribe from an event."""
    with _lock:
        if event in _subscribers:
            _subscribers[event][:] = [
                r for r in _subscribers[event] if r() is not None and r() != callback
            ]


def emit(event: str, data: Any = None) -> int:
    """Emit an event. Returns number of delivered callbacks."""
    with _lock:
        refs = list(_subscribers.get(event, []))

    delivered = 0
    for ref in refs:
        cb = ref()
        if cb is None:
            continue
        try:
            cb(data)
            delivered += 1
        except Exception:
            pass
    return delivered
