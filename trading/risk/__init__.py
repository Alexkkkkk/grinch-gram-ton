"""Risk management — stops, trailing, circuit breakers."""

# Single canonical definition: the repo-root `circuit_breaker` module.
# trading/risk/circuit_breaker.py previously held a *second* CircuitBreaker class.
from circuit_breaker import CircuitBreaker  # noqa: F401

from .sizing import PositionSizer
from .stop_loss import StopLossEngine
from .trailing import TrailingStopEngine

__all__ = ["StopLossEngine", "TrailingStopEngine", "CircuitBreaker", "PositionSizer"]
