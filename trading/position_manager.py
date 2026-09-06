"""Position manager stub — created during v3.1 audit fix."""

from typing import Any


class PositionManager:
    """Minimal position manager to satisfy imports."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize empty position manager."""
        self.positions: list[dict[str, Any]] = []

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return currently open positions."""
        return self.positions

    def add_position(self, position: dict[str, Any]) -> None:
        """Add a new position."""
        self.positions.append(position)

    def close_position(self, idx: int) -> dict[str, Any] | None:
        """Close position by index and return it."""
        if 0 <= idx < len(self.positions):
            return self.positions.pop(idx)
        return None
