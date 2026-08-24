"""Central event bus — breaks circular imports between modules."""

import threading
from typing import Any, Callable, Dict, List

_subscribers: Dict[str, List[Callable[[Any], None]]] = {}
_lock = threading.RLock()

# Event names
EVENT_AI_SIGNAL = "ai.signal"
EVENT_TRADE_CLOSED = "trade.closed"
EVENT_FUSION_UPDATE = "fusion.update"
EVENT_TRADE_OPENED = "trade.opened"
EVENT_CONFIG_CHANGED = "config.changed"
EVENT_PRICE_UPDATE = "price.update"


def subscribe(event: str, callback: Callable[[Any], None]) -> None:
    """Subscribe to an event. Thread-safe."""
    with _lock:
        _subscribers.setdefault(event, []).append(callback)


def unsubscribe(event: str, callback: Callable[[Any], None]) -> None:
    """Unsubscribe from an event."""
    with _lock:
        if event in _subscribers:
            try:
                _subscribers[event].remove(callback)
            except ValueError:
                pass


def emit(event: str, data: Any = None) -> None:
    """Emit an event to all subscribers. Exceptions are swallowed."""
    with _lock:
        cbs = list(_subscribers.get(event, []))
    for cb in cbs:
        try:
            cb(data)
        except Exception:
            pass
