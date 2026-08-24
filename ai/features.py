"""Feature extraction for AI engine — technical indicators as numpy arrays."""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def extract_features(ohlcv: list[dict], n_features: int = 32) -> np.ndarray | None:
    """Convert OHLCV list into a feature vector for ML models."""
    if not ohlcv or len(ohlcv) < 20:
        return None
    df = pd.DataFrame(ohlcv)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna()
    if len(df) < 20:
        return None
    close = df["close"].values
    volume = df["volume"].values
    # Returns
    returns = np.diff(close) / close[:-1]
    # Simple features
    features = [
        close[-1] / close[-20] - 1.0,  # 20-period return
        close[-1] / close[-5] - 1.0,  # 5-period return
        np.mean(returns[-10:]),  # mean return
        np.std(returns[-10:]),  # volatility
        np.mean(returns[-20:]),
        np.std(returns[-20:]),
        float(volume[-1]) / (float(np.mean(volume[-20:])) + 1e-9),  # volume ratio
        (close[-1] - np.min(close[-20:]))
        / (np.max(close[-20:]) - np.min(close[-20:]) + 1e-9),  # position in range
        (close[-1] - np.mean(close[-20:])) / (np.std(close[-20:]) + 1e-9),  # z-score
    ]
    # Pad or truncate to n_features
    if len(features) < n_features:
        features.extend([0.0] * (n_features - len(features)))
    return np.array(features[:n_features], dtype=np.float32).reshape(1, -1)


def build_training_data(ohlcv: list[dict], profit_bias_pct: float = 2.0) -> tuple:
    """Build X, y arrays from OHLCV for supervised learning."""
    if len(ohlcv) < 30:
        return None, None
    df = pd.DataFrame(ohlcv)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            return None, None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna()
    if len(df) < 30:
        return None, None
    close = df["close"].values
    X, y = [], []
    for i in range(20, len(close) - 5):
        window = [
            {"close": c, "volume": v}
            for c, v in zip(close[i - 20 : i], df["volume"].values[i - 20 : i])
        ]
        feat = extract_features(window)
        if feat is None:
            continue
        # Label: 1 if price rises >= profit_bias_pct in next 5 bars
        future_return = (close[i + 5] - close[i]) / close[i] * 100
        label = 1 if future_return >= profit_bias_pct else 0
        X.append(feat[0])
        y.append(label)
    if len(X) < 10:
        return None, None
    return np.array(X), np.array(y)
