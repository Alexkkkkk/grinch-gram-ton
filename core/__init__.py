"""Core package — shared infrastructure for GRINCH-GRAM v3.0."""

from .base_components import BaseWorker, GridLevel, NpEncoder
from .config import (
    Config,
    FeeConfig,
    GridConfig,
    TrailConfig,
    DcaConfig,
    AiConfig,
    SmartConfig,
    ProtectionConfig,
    ShortConfig,
    ScalpConfig,
    FusionConfig,
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
