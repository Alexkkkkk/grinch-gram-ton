"""Ensemble manager — coordinates multiple model wrappers."""

import logging

import numpy as np

from .base import BaseModelWrapper

logger = logging.getLogger(__name__)


class EnsembleManager:
    """Weighted ensemble of model wrappers with accuracy tracking."""

    __slots__ = ("_models", "_weights")

    def __init__(self) -> None:
        self._models: dict[str, BaseModelWrapper] = {}
        self._weights: dict[str, float] = {}

    def add(self, model: BaseModelWrapper, weight: float = 1.0) -> None:
        self._models[model.name] = model
        self._weights[model.name] = weight

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        for name, model in self._models.items():
            try:
                model.fit(X, y)
                logger.info("[Ensemble] %s trained (n=%d)", name, len(y))
            except Exception as exc:
                logger.warning("[Ensemble] %s train failed: %s", name, exc)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        probs: list[np.ndarray] = []
        weights: list[float] = []
        for name, model in self._models.items():
            if not model.is_trained:
                continue
            p = model.predict_proba(X)
            if p is not None and p.shape[1] >= 2:
                probs.append(p)
                # Dynamic weight: accuracy-based boost
                acc = model.accuracy
                w = self._weights.get(name, 1.0) * (0.5 + acc) if acc > 0 else 1.0
                weights.append(max(0.1, w))
        if not probs:
            return np.array([[0.5, 0.5]])
        weights = np.array(weights)
        weights /= weights.sum()
        stacked = np.stack(probs, axis=0)
        return np.average(stacked, axis=0, weights=weights)

    def record(self, predictions: dict[str, bool]) -> None:
        for name, correct in predictions.items():
            if name in self._models:
                self._models[name].record(correct)

    @property
    def status(self) -> dict[str, Any]:
        return {
            name: {
                "trained": m.is_trained,
                "accuracy": m.accuracy,
                "samples": m._samples,
            }
            for name, m in self._models.items()
        }
