"""AI package — lazy-loaded ML engine for GRINCH-GRAM."""

import logging

logger = logging.getLogger(__name__)
_ai_engine = None


def get_ai_engine():
    """Lazy singleton — sklearn/xgboost loaded only on first call."""
    global _ai_engine
    if _ai_engine is None:
        from ai.engine import AIEngine
        _ai_engine = AIEngine()
    return _ai_engine


# Back-compat re-export
__all__ = ["get_ai_engine", "AIEngine"]
