"""Base model wrapper — eliminates fit/predict/record/accuracy duplication."""

from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class BaseModelWrapper(ABC):
    """Unified interface for any sklearn-compatible classifier."""

    __slots__ = ("_name", "_model", "_trained", "_samples", "_correct")

    def __init__(self, name: str) -> None:
        self._name: str = name
        self._model: Any | None = None
        self._trained: bool = False
        self._samples: int = 0
        self._correct: int = 0

    @abstractmethod
    def _build(self) -> Any:
        """Return a fresh untrained model instance."""
        raise NotImplementedError

    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaseModelWrapper":
        self._model = self._build()
        self._model.fit(X, y)
        self._trained = True
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._trained or self._model is None:
            return np.array([[0.5, 0.5]])
        try:
            return self._model.predict_proba(X)
        except Exception:
            return np.array([[0.5, 0.5]])

    @property
    def classes_(self):
        return self._model.classes_ if self._model is not None else []

    def record(self, correct: bool) -> None:
        self._samples += 1
        if correct:
            self._correct += 1

    @property
    def accuracy(self) -> float:
        return self._correct / self._samples if self._samples > 0 else 0.0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_trained(self) -> bool:
        return self._trained


class SklearnWrapper(BaseModelWrapper):
    """Wrapper for any sklearn estimator class."""

    __slots__ = ("_cls", "_kwargs")

    def __init__(self, name: str, cls, **kwargs) -> None:
        super().__init__(name)
        self._cls = cls
        self._kwargs = kwargs

    def _build(self) -> Any:
        return self._cls(**self._kwargs)
