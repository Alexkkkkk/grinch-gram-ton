"""
ai/ — Quantum Intelligence Suite v7

Модули:
  • engine.py          — ML ансамбль (RF/ET/GB/HGB/XGB/MLP)
  • features.py        — Извлечение признаков из OHLCV
  • regime.py          — Детекция режима рынка
  • neural_prophet.py  — Нейронное предсказание цен (LSTM-like через sklearn)
  • sentiment.py       — Анализ настроений рынка (Fear&Greed, Order Flow)
  • quantum_optimizer.py — Квантовая оптимизация параметров сетки
  • swarm.py           — Рой интеллектуальных агентов
  • xai_explainer.py   — Объяснимый ИИ (SHAP-like, Trust Score)
"""

from ai.engine import AIEngine as QuantumEngine
from ai.features import extract_features
from ai.neural_prophet import get_full_prediction, get_prophet, predict_price
from ai.quantum_optimizer import get_optimizer, get_recommended_params, optimize_grid
from ai.regime import BreakoutEngine, MomentumEngine, PumpDetector
from ai.sentiment import analyze as analyze_sentiment
from ai.sentiment import get_sentiment
from ai.swarm import analyze as analyze_swarm
from ai.swarm import feedback as swarm_feedback
from ai.swarm import get_swarm
from ai.xai_explainer import explain, get_xai

__all__ = [
    "QuantumEngine",
    "extract_features",
    "get_prophet",
    "predict_price",
    "get_full_prediction",
    "get_optimizer",
    "optimize_grid",
    "get_recommended_params",
    "BreakoutEngine",
    "MomentumEngine",
    "PumpDetector",
    "get_sentiment",
    "analyze_sentiment",
    "get_swarm",
    "analyze_swarm",
    "swarm_feedback",
    "get_xai",
    "explain",
]
