"""
swarm.py v1 — QuantumSwarm: Рой интеллектуальных агентов.

Архитектура:
  1. SwarmAgent       — индивидуальный агент со своей стратегией
  2. StrategyGenome   — генетическое кодирование стратегии
  3. SwarmConsensus  — взвешенное голосование роя
  4. EvolutionEngine  — эволюция агентов через отбор

Каждый агент — это мини-трейдер с уникальным набором параметров.
Рой голосует за BUY/SELL/HOLD, вес агента зависит от его track record.
"""

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger("swarm")

# ── Константы ────────────────────────────────────────────────────────────────
SWARM_SIZE = 16  # размер роя
EVOLUTION_EVERY = 20  # эволюция каждые N тиков
MUTATION_RATE = 0.15  # вероятность мутации гена
CROSSOVER_RATE = 0.3  # вероятность скрещивания
AGENT_MEMORY = 30  # сколько предсказаний помнит агент


@dataclass
class StrategyGenome:
    """Генетический код стратегии агента."""

    # Технические параметры
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    ema_fast: int = 9
    ema_slow: int = 21
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14

    # Пороги сигналов
    trend_threshold: float = 0.5  # % разницы EMA для тренда
    momentum_threshold: float = 1.0  # % для моментума
    volume_threshold: float = 1.5  # множитель объёма

    # Веса сигналов
    w_rsi: float = 1.0
    w_ema: float = 1.0
    w_bb: float = 1.0
    w_volume: float = 0.5
    w_momentum: float = 0.8

    # Параметры риска
    confidence_threshold: float = 55.0
    max_position_pct: float = 0.25

    def mutate(
        self, rate: float = MUTATION_RATE, rng: random.Random = None
    ) -> "StrategyGenome":
        r = rng or random.Random()
        g = StrategyGenome(
            rsi_period=max(5, min(30, self.rsi_period + r.randint(-3, 3))),
            rsi_overbought=max(60, min(90, self.rsi_overbought + r.gauss(0, 3))),
            rsi_oversold=max(10, min(40, self.rsi_oversold + r.gauss(0, 3))),
            ema_fast=max(3, min(20, self.ema_fast + r.randint(-2, 2))),
            ema_slow=max(10, min(50, self.ema_slow + r.randint(-3, 3))),
            bb_period=max(10, min(40, self.bb_period + r.randint(-3, 3))),
            bb_std=max(1.0, min(3.5, self.bb_std + r.gauss(0, 0.3))),
            atr_period=max(5, min(30, self.atr_period + r.randint(-2, 2))),
            trend_threshold=max(0.1, min(2.0, self.trend_threshold + r.gauss(0, 0.2))),
            momentum_threshold=max(
                0.1, min(5.0, self.momentum_threshold + r.gauss(0, 0.3))
            ),
            volume_threshold=max(
                0.5, min(5.0, self.volume_threshold + r.gauss(0, 0.3))
            ),
            w_rsi=max(0, min(3, self.w_rsi + r.gauss(0, 0.2))),
            w_ema=max(0, min(3, self.w_ema + r.gauss(0, 0.2))),
            w_bb=max(0, min(3, self.w_bb + r.gauss(0, 0.2))),
            w_volume=max(0, min(3, self.w_volume + r.gauss(0, 0.2))),
            w_momentum=max(0, min(3, self.w_momentum + r.gauss(0, 0.2))),
            confidence_threshold=max(
                30, min(80, self.confidence_threshold + r.gauss(0, 5))
            ),
            max_position_pct=max(
                0.05, min(1.0, self.max_position_pct + r.gauss(0, 0.05))
            ),
        )
        return g

    @classmethod
    def random(cls, rng: random.Random = None) -> "StrategyGenome":
        r = rng or random.Random()
        return cls(
            rsi_period=r.randint(8, 25),
            rsi_overbought=r.uniform(65, 85),
            rsi_oversold=r.uniform(15, 35),
            ema_fast=r.randint(5, 15),
            ema_slow=r.randint(15, 35),
            bb_period=r.randint(15, 30),
            bb_std=r.uniform(1.5, 2.5),
            atr_period=r.randint(10, 20),
            trend_threshold=r.uniform(0.2, 1.0),
            momentum_threshold=r.uniform(0.5, 2.0),
            volume_threshold=r.uniform(1.0, 2.5),
            w_rsi=r.uniform(0.5, 2.0),
            w_ema=r.uniform(0.5, 2.0),
            w_bb=r.uniform(0.3, 1.5),
            w_volume=r.uniform(0.2, 1.0),
            w_momentum=r.uniform(0.3, 1.5),
            confidence_threshold=r.uniform(45, 70),
            max_position_pct=r.uniform(0.1, 0.5),
        )

    def to_dict(self) -> dict:
        return {
            "rsi_period": self.rsi_period,
            "rsi_overbought": round(self.rsi_overbought, 2),
            "rsi_oversold": round(self.rsi_oversold, 2),
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "bb_period": self.bb_period,
            "bb_std": round(self.bb_std, 2),
            "trend_threshold": round(self.trend_threshold, 4),
            "momentum_threshold": round(self.momentum_threshold, 4),
            "volume_threshold": round(self.volume_threshold, 4),
            "w_rsi": round(self.w_rsi, 3),
            "w_ema": round(self.w_ema, 3),
            "w_bb": round(self.w_bb, 3),
            "w_volume": round(self.w_volume, 3),
            "w_momentum": round(self.w_momentum, 3),
            "confidence": round(self.confidence_threshold, 2),
            "max_position": round(self.max_position_pct, 3),
        }


@dataclass
class AgentPrediction:
    signal: str = "HOLD"  # BUY / SELL / HOLD
    confidence: float = 0.0  # 0-100
    reasoning: str = ""
    timestamp: float = 0.0


class SwarmAgent:
    """Индивидуальный агент роя."""

    def __init__(self, agent_id: int, genome: Optional[StrategyGenome] = None):
        self.id = agent_id
        self.genome = genome or StrategyGenome.random()
        self._predictions: deque = deque(maxlen=AGENT_MEMORY)
        self._correct_predictions = 0
        self._total_predictions = 0
        self._fitness = 0.5
        self._lock = threading.RLock()

    def analyze(self, candles: List[dict]) -> AgentPrediction:
        """Анализировать рынок и вернуть сигнал."""
        if (
            len(candles)
            < max(self.genome.ema_slow, self.genome.bb_period, self.genome.rsi_period)
            + 5
        ):
            return AgentPrediction(
                signal="HOLD", confidence=0.0, reasoning="Недостаточно данных"
            )

        closes = np.array([float(c.get("close", c.get("c", 0))) for c in candles])
        volumes = np.array([float(c.get("volume", c.get("v", 0))) for c in candles])
        highs = np.array([float(c.get("high", c.get("h", 0))) for c in candles])
        lows = np.array([float(c.get("low", c.get("l", 0))) for c in candles])

        scores = {"buy": 0.0, "sell": 0.0}
        reasons = []

        # 1. RSI
        try:
            delta = np.diff(closes)
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = np.mean(gain[-self.genome.rsi_period :])
            avg_loss = np.mean(loss[-self.genome.rsi_period :]) + 1e-9
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            if rsi < self.genome.rsi_oversold:
                scores["buy"] += (
                    self.genome.w_rsi
                    * (self.genome.rsi_oversold - rsi)
                    / self.genome.rsi_oversold
                )
                reasons.append(f"RSI oversold ({rsi:.1f})")
            elif rsi > self.genome.rsi_overbought:
                scores["sell"] += (
                    self.genome.w_rsi
                    * (rsi - self.genome.rsi_overbought)
                    / (100 - self.genome.rsi_overbought)
                )
                reasons.append(f"RSI overbought ({rsi:.1f})")
        except Exception:
            pass

        # 2. EMA crossover
        try:
            ema_fast = np.mean(closes[-self.genome.ema_fast :])
            ema_slow = np.mean(closes[-self.genome.ema_slow :])
            trend = (ema_fast - ema_slow) / ema_slow * 100

            if trend > self.genome.trend_threshold:
                scores["buy"] += self.genome.w_ema * min(
                    2.0, trend / self.genome.trend_threshold
                )
                reasons.append(f"EMA bullish ({trend:.2f}%)")
            elif trend < -self.genome.trend_threshold:
                scores["sell"] += self.genome.w_ema * min(
                    2.0, abs(trend) / self.genome.trend_threshold
                )
                reasons.append(f"EMA bearish ({trend:.2f}%)")
        except Exception:
            pass

        # 3. Bollinger Bands
        try:
            bb_window = closes[-self.genome.bb_period :]
            bb_mid = np.mean(bb_window)
            bb_std = np.std(bb_window) * self.genome.bb_std
            bb_upper = bb_mid + bb_std
            bb_lower = bb_mid - bb_std
            price = closes[-1]

            if price < bb_lower:
                scores["buy"] += self.genome.w_bb * (bb_lower - price) / (bb_std + 1e-9)
                reasons.append(f"BB bounce ({price:.4f} < {bb_lower:.4f})")
            elif price > bb_upper:
                scores["sell"] += (
                    self.genome.w_bb * (price - bb_upper) / (bb_std + 1e-9)
                )
                reasons.append(f"BB reverse ({price:.4f} > {bb_upper:.4f})")
        except Exception:
            pass

        # 4. Volume anomaly
        try:
            vol_recent = np.mean(volumes[-3:])
            vol_hist = np.mean(volumes[-20:])
            if vol_hist > 0 and vol_recent > vol_hist * self.genome.volume_threshold:
                # Высокий объём на росте = покупки
                price_change = (closes[-1] - closes[-3]) / closes[-3] * 100
                if price_change > 0:
                    scores["buy"] += self.genome.w_volume
                    reasons.append("Volume spike +price")
                else:
                    scores["sell"] += self.genome.w_volume
                    reasons.append("Volume spike -price")
        except Exception:
            pass

        # 5. Momentum
        try:
            mom = (closes[-1] - closes[-5]) / closes[-5] * 100
            if mom > self.genome.momentum_threshold:
                scores["buy"] += self.genome.w_momentum * min(
                    2.0, mom / self.genome.momentum_threshold
                )
                reasons.append(f"Momentum up ({mom:.2f}%)")
            elif mom < -self.genome.momentum_threshold:
                scores["sell"] += self.genome.w_momentum * min(
                    2.0, abs(mom) / self.genome.momentum_threshold
                )
                reasons.append(f"Momentum down ({mom:.2f}%)")
        except Exception:
            pass

        # Определяем сигнал
        total_buy = scores["buy"]
        total_sell = scores["sell"]
        max_score = max(total_buy, total_sell, 0.1)

        if total_buy > total_sell and total_buy > 0.5:
            conf = min(100, total_buy * 20)
            if conf >= self.genome.confidence_threshold:
                pred = AgentPrediction(
                    signal="BUY",
                    confidence=conf,
                    reasoning="; ".join(reasons) or "buy signal",
                    timestamp=time.time(),
                )
            else:
                pred = AgentPrediction(
                    signal="HOLD", confidence=conf, reasoning="Low confidence"
                )
        elif total_sell > total_buy and total_sell > 0.5:
            conf = min(100, total_sell * 20)
            if conf >= self.genome.confidence_threshold:
                pred = AgentPrediction(
                    signal="SELL",
                    confidence=conf,
                    reasoning="; ".join(reasons) or "sell signal",
                    timestamp=time.time(),
                )
            else:
                pred = AgentPrediction(
                    signal="HOLD", confidence=conf, reasoning="Low confidence"
                )
        else:
            pred = AgentPrediction(
                signal="HOLD", confidence=0.0, reasoning="No clear signal"
            )

        with self._lock:
            self._predictions.append(pred)
            self._total_predictions += 1

        return pred

    def update_fitness(self, actual_direction: str):
        """Обновить фитнес на основе реального исхода."""
        with self._lock:
            if not self._predictions:
                return
            last = self._predictions[-1]
            if last.signal == actual_direction:
                self._correct_predictions += 1
                self._fitness = min(1.0, self._fitness + 0.05)
            else:
                self._fitness = max(0.0, self._fitness - 0.03)

    @property
    def fitness(self) -> float:
        with self._lock:
            if self._total_predictions > 0:
                return self._correct_predictions / max(self._total_predictions, 1)
            return self._fitness

    @property
    def weight(self) -> float:
        """Вес агента в голосовании = fitness^2 (лучшие имеют больше влияния)."""
        return self.fitness**2 + 0.1  # +0.1 чтобы новые агенты тоже имели голос

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fitness": round(self.fitness, 4),
            "weight": round(self.weight, 4),
            "predictions": self._total_predictions,
            "correct": self._correct_predictions,
            "genome": self.genome.to_dict(),
        }


class EvolutionEngine:
    """Эволюция роя: отбор, скрещивание, мутация."""

    def __init__(self):
        self._rng = random.Random()

    def evolve(self, agents: List[SwarmAgent]) -> List[SwarmAgent]:
        """Создать новое поколение агентов."""
        # Сортируем по фитнесу
        sorted_agents = sorted(agents, key=lambda a: a.fitness, reverse=True)
        n = len(sorted_agents)

        # Элитизм: топ-25% сохраняем
        elite_count = max(1, n // 4)
        new_agents = sorted_agents[:elite_count]

        # Остальные — скрещивание + мутация
        while len(new_agents) < n:
            # Турнирный отбор
            parent1 = self._tournament_select(sorted_agents)
            parent2 = self._tournament_select(sorted_agents)

            if self._rng.random() < CROSSOVER_RATE:
                child_genome = self._crossover(parent1.genome, parent2.genome)
            else:
                child_genome = parent1.genome.copy()

            if self._rng.random() < MUTATION_RATE:
                child_genome = child_genome.mutate(rng=self._rng)

            new_agents.append(SwarmAgent(len(new_agents), child_genome))

        logger.info(
            "[EvolutionEngine] Новое поколение: elite=%d, avg_fitness=%.3f",
            elite_count,
            np.mean([a.fitness for a in new_agents]),
        )
        return new_agents

    def _tournament_select(self, agents: List[SwarmAgent], k: int = 3) -> SwarmAgent:
        """Турнирный отбор: выбираем лучшего из k случайных."""
        tournament = self._rng.sample(agents, min(k, len(agents)))
        return max(tournament, key=lambda a: a.fitness)

    def _crossover(self, g1: StrategyGenome, g2: StrategyGenome) -> StrategyGenome:
        """Скрещивание двух геномов (uniform crossover)."""
        r = self._rng
        return StrategyGenome(
            rsi_period=g1.rsi_period if r.random() < 0.5 else g2.rsi_period,
            rsi_overbought=g1.rsi_overbought if r.random() < 0.5 else g2.rsi_overbought,
            rsi_oversold=g1.rsi_oversold if r.random() < 0.5 else g2.rsi_oversold,
            ema_fast=g1.ema_fast if r.random() < 0.5 else g2.ema_fast,
            ema_slow=g1.ema_slow if r.random() < 0.5 else g2.ema_slow,
            bb_period=g1.bb_period if r.random() < 0.5 else g2.bb_period,
            bb_std=g1.bb_std if r.random() < 0.5 else g2.bb_std,
            atr_period=g1.atr_period if r.random() < 0.5 else g2.atr_period,
            trend_threshold=(
                g1.trend_threshold if r.random() < 0.5 else g2.trend_threshold
            ),
            momentum_threshold=(
                g1.momentum_threshold if r.random() < 0.5 else g2.momentum_threshold
            ),
            volume_threshold=(
                g1.volume_threshold if r.random() < 0.5 else g2.volume_threshold
            ),
            w_rsi=g1.w_rsi if r.random() < 0.5 else g2.w_rsi,
            w_ema=g1.w_ema if r.random() < 0.5 else g2.w_ema,
            w_bb=g1.w_bb if r.random() < 0.5 else g2.w_bb,
            w_volume=g1.w_volume if r.random() < 0.5 else g2.w_volume,
            w_momentum=g1.w_momentum if r.random() < 0.5 else g2.w_momentum,
            confidence_threshold=(
                g1.confidence_threshold if r.random() < 0.5 else g2.confidence_threshold
            ),
            max_position_pct=(
                g1.max_position_pct if r.random() < 0.5 else g2.max_position_pct
            ),
        )


class QuantumSwarm:
    """Единый движок роя."""

    def __init__(self, size: int = SWARM_SIZE):
        self._agents: List[SwarmAgent] = [SwarmAgent(i) for i in range(size)]
        self._evolution = EvolutionEngine()
        self._tick_count = 0
        self._lock = threading.RLock()
        self._last_consensus: dict = {}

    def analyze(self, candles: List[dict]) -> dict:
        """Получить консенсус роя."""
        with self._lock:
            self._tick_count += 1

            # Собираем голоса
            votes: Dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
            agent_signals = []

            for agent in self._agents:
                pred = agent.analyze(candles)
                weight = agent.weight
                votes[pred.signal] += weight * pred.confidence
                agent_signals.append(
                    {
                        "id": agent.id,
                        "signal": pred.signal,
                        "confidence": round(pred.confidence, 2),
                        "weight": round(weight, 4),
                        "reasoning": pred.reasoning,
                    }
                )

            total_weight = sum(votes.values())
            if total_weight < 1e-9:
                consensus = "HOLD"
                consensus_conf = 0.0
            else:
                # Нормализуем
                for k in votes:
                    votes[k] /= total_weight

                consensus = max(votes, key=votes.get)
                consensus_conf = votes[consensus] * 100

            # Эволюция
            if self._tick_count % EVOLUTION_EVERY == 0:
                self._agents = self._evolution.evolve(self._agents)

            result = {
                "consensus": consensus,
                "confidence": round(consensus_conf, 2),
                "vote_distribution": {k: round(v, 4) for k, v in votes.items()},
                "agents_count": len(self._agents),
                "avg_fitness": round(np.mean([a.fitness for a in self._agents]), 4),
                "best_fitness": round(max(a.fitness for a in self._agents), 4),
                "agent_signals": agent_signals[:8],  # топ-8 для детализации
            }
            self._last_consensus = result
            return result

    def feedback(self, actual_direction: str):
        """Обратная связь: обновить фитнес агентов."""
        with self._lock:
            for agent in self._agents:
                agent.update_fitness(actual_direction)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "consensus": self._last_consensus,
                "agents": [a.to_dict() for a in self._agents],
                "tick_count": self._tick_count,
            }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════
_swarm: Optional[QuantumSwarm] = None


def get_swarm() -> QuantumSwarm:
    global _swarm
    if _swarm is None:
        _swarm = QuantumSwarm()
    return _swarm


def analyze(candles: List[dict]) -> dict:
    """Публичный API: получить консенсус роя."""
    swarm = get_swarm()
    return swarm.analyze(candles)


def feedback(actual_direction: str):
    """Публичный API: обратная связь."""
    swarm = get_swarm()
    swarm.feedback(actual_direction)
