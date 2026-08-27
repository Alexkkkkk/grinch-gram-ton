"""Market analysis — signals, trends, confluence."""

from .confluence import ConfluenceFilter
from .signal import SignalGenerator
from .trend import TrendAnalyzer

__all__ = ["SignalGenerator", "TrendAnalyzer", "ConfluenceFilter"]
