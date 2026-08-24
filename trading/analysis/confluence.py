"""Confluence filter — require multiple confirmations."""
import logging

logger = logging.getLogger(__name__)


class ConfluenceFilter:
    """Require multiple indicators to align before trading."""

    def __init__(self, config=None):
        self.config = config

    def check(self, signals: dict) -> bool:
        """Return True if enough confluence for trade."""
        if not self.config or not getattr(self.config, "enabled", True):
            return True
        min_conf = getattr(self.config, "min_confidence", 50)
        score = signals.get("confidence", 0)
        return score >= min_conf
