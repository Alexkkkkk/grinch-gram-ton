"""Core package — shared infrastructure for AI-Trading v3.0."""

from .base_components import BaseWorker, GridLevel, NpEncoder
from .config import (
    AiConfig,
    Config,
    DcaConfig,
    FeeConfig,
    FusionConfig,
    GridConfig,
    ProtectionConfig,
    ScalpConfig,
    ShortConfig,
    SmartConfig,
    TrailConfig,
)
from .events import emit, subscribe

__all__ = [
    "BaseWorker",
    "GridLevel",
    "NpEncoder",
    "Config",
    "FeeConfig",
    "GridConfig",
    "TrailConfig",
    "DcaConfig",
    "AiConfig",
    "SmartConfig",
    "ProtectionConfig",
    "ShortConfig",
    "ScalpConfig",
    "FusionConfig",
    "emit",
    "subscribe",
]
