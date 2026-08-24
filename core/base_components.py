"""Shared base classes — eliminates duplication across modules."""

import json
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class NpEncoder(json.JSONEncoder):
    """Unified NumPy JSON encoder — replaces _NpEncoder duplicates."""

    def default(self, o: Any) -> Any:
        import numpy as np

        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
        return super().default(o)


class GridLevel:
    """Unified grid level — replaces duplicates in grid_trader / binance_grid_engine."""

    __slots__ = ("price", "side", "amount", "filled", "order_id")

    def __init__(self, price: float, side: str, amount: float) -> None:
        self.price: float = price
        self.side: str = side
        self.amount: float = amount
        self.filled: bool = False
        self.order_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "price": self.price,
            "side": self.side,
            "amount": self.amount,
            "filled": self.filled,
            "order_id": self.order_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GridLevel":
        obj = cls(d["price"], d["side"], d["amount"])
        obj.filled = d.get("filled", False)
        obj.order_id = d.get("order_id")
        return obj


class BaseWorker(ABC):
    """Base class for all background workers — unifies start/stop/is_alive."""

    __slots__ = ("_name", "_thread", "_stop_event", "_running", "_interval_sec")

    def __init__(self, name: str, interval_sec: float = 15.0) -> None:
        self._name: str = name
        self._interval_sec: float = interval_sec
        self._thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        self._running: bool = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_wrapper, name=f"worker-{self._name}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_wrapper(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                print(f"[{self._name}] Error: {exc}")
            self._stop_event.wait(timeout=self._interval_sec)

    @abstractmethod
    def _tick(self) -> None:
        """Override in subclass — called every interval."""
        raise NotImplementedError

    def get_status(self) -> Dict[str, Any]:
        return {"name": self._name, "running": self._running, "alive": self.is_alive}
