"""Shared base classes — eliminates duplication, memory-optimized."""

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class NpEncoder(json.JSONEncoder):
    """Unified NumPy JSON encoder."""

    def default(self, o: Any) -> Any:
        import numpy as np

        if isinstance(o, (np.integer, np.int8, np.int16, np.int32, np.int64)):
            return int(o)
        if isinstance(o, (np.floating, np.float16, np.float32, np.float64)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, (np.datetime64,)):
            return str(o)
        return super().default(o)


class GridLevel:
    """Memory-optimized grid level with __slots__."""

    __slots__ = ("price", "side", "amount", "filled", "order_id", "created_at")

    def __init__(self, price: float, side: str, amount: float) -> None:
        self.price: float = price
        self.side: str = side
        self.amount: float = amount
        self.filled: bool = False
        self.order_id: str | None = None
        self.created_at: float = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "side": self.side,
            "amount": self.amount,
            "filled": self.filled,
            "order_id": self.order_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GridLevel":
        obj = cls(d["price"], d["side"], d["amount"])
        obj.filled = d.get("filled", False)
        obj.order_id = d.get("order_id")
        obj.created_at = d.get("created_at", time.time())
        return obj

    def __repr__(self) -> str:
        return f"GridLevel({self.price:.8f}, {self.side}, filled={self.filled})"


class BaseWorker(ABC):
    """Base class for all background workers — unified lifecycle."""

    __slots__ = (
        "_name",
        "_thread",
        "_stop_event",
        "_running",
        "_interval_sec",
        "_logger",
    )

    def __init__(self, name: str, interval_sec: float = 15.0) -> None:
        self._name: str = name
        self._interval_sec: float = interval_sec
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event = threading.Event()
        self._running: bool = False
        self._logger = logging.getLogger(f"worker.{name}")

    def start(self) -> None:
        if self._running:
            self._logger.warning("Already running")
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_wrapper, name=f"worker-{self._name}", daemon=True
        )
        self._thread.start()
        self._logger.info("Started (interval=%.1fs)", self._interval_sec)

    def stop(self, timeout: float = 5.0) -> bool:
        """Graceful stop with timeout. Returns True if stopped cleanly."""
        if not self._running:
            return True
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                self._logger.warning("Did not stop within %.1fs", timeout)
                return False
        self._logger.info("Stopped")
        return True

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_wrapper(self) -> None:
        while not self._stop_event.is_set():
            start = time.time()
            try:
                self._tick()
            except Exception as exc:
                self._logger.error("Tick error: %s", exc, exc_info=True)
            elapsed = time.time() - start
            sleep_for = max(0.0, self._interval_sec - elapsed)
            self._stop_event.wait(timeout=sleep_for)

    @abstractmethod
    def _tick(self) -> None:
        raise NotImplementedError

    def get_status(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "running": self._running,
            "alive": self.is_alive,
            "interval_sec": self._interval_sec,
        }
