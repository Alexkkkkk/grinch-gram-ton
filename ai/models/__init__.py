"""AI model wrappers — unified interface for all ML models."""

from .base import BaseModelWrapper
from .ensemble import EnsembleManager

__all__ = ["BaseModelWrapper", "EnsembleManager"]
