"""Market regime detection — momentum, breakout, pump detection."""

import logging

import numpy as np

logger = logging.getLogger(__name__)


class MomentumEngine:
    """Detects momentum regime from price series."""

    @staticmethod
    def detect(close: np.ndarray) -> dict[str, any]:
        if len(close) < 10:
            return {"signal": "CALM", "score": 0.0}
        ret_5 = (close[-1] - close[-5]) / close[-5] * 100 if close[-5] > 0 else 0
        ret_10 = (close[-1] - close[-10]) / close[-10] * 100 if close[-10] > 0 else 0
        if ret_5 > 5 and ret_10 > 10:
            signal = "EXPLOSIVE"
        elif ret_5 > 2 and ret_10 > 5:
            signal = "SURGE"
        elif ret_5 > 0.5:
            signal = "BUILDING"
        else:
            signal = "CALM"
        score = min(1.0, abs(ret_10) / 20.0)
        return {"signal": signal, "score": score, "ret_5": ret_5, "ret_10": ret_10}


class BreakoutEngine:
    """Detects breakout patterns."""

    @staticmethod
    def detect(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> dict[str, any]:
        if len(close) < 20:
            return {"signal": "FLAT", "score": 0.0}
        upper = np.max(high[-20:-1])
        lower = np.min(low[-20:-1])
        range_pct = (upper - lower) / lower * 100 if lower > 0 else 0
        if close[-1] > upper * 1.01:
            signal = "BREAKOUT"
            score = min(1.0, (close[-1] - upper) / upper * 100 / 5.0)
        elif close[-1] > upper * 0.995 and range_pct < 5:
            signal = "RUNAWAY"
            score = 0.6
        else:
            signal = "FLAT"
            score = 0.0
        return {"signal": signal, "score": score, "range_pct": range_pct}


class PumpDetector:
    """Detects pump conditions (volume + price acceleration)."""

    @staticmethod
    def detect(close: np.ndarray, volume: np.ndarray) -> dict[str, any]:
        if len(close) < 10 or len(volume) < 10:
            return {"score": 0.0, "detected": False}
        vol_ma = np.mean(volume[-10:-1])
        vol_now = volume[-1]
        price_change = (close[-1] - close[-5]) / close[-5] * 100 if close[-5] > 0 else 0
        vol_spike = vol_now / (vol_ma + 1e-9) > 2.0
        price_spike = price_change > 3.0
        score = 0.0
        if vol_spike:
            score += 0.4
        if price_spike:
            score += 0.6
        return {
            "score": score * 100,
            "detected": score > 0.5,
            "vol_spike": vol_spike,
            "price_spike": price_spike,
        }
