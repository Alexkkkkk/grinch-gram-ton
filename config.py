"""Backward-compat shim — delegates to core.config.Config."""
from core.config import Config, FeeConfig, GridConfig, TrailConfig, DcaConfig, AiConfig, SmartConfig, ProtectionConfig, ShortConfig, ScalpConfig, FusionConfig

import sys
_mod = sys.modules[__name__]

# Copy all public attributes from Config singleton instance
for _attr in dir(Config()):
    if _attr.startswith("_"):
        continue
    try:
        val = getattr(Config, _attr)
        setattr(_mod, _attr, val)
    except Exception:
        pass
