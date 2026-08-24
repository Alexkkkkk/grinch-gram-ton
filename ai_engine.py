"""Backward-compat shim — delegates to ai package."""
from ai.engine import AIEngine
from ai.features import extract_features, build_training_data
from ai.regime import MomentumEngine, BreakoutEngine, PumpDetector

__all__ = ["AIEngine", "extract_features", "build_training_data", "MomentumEngine", "BreakoutEngine", "PumpDetector"]
