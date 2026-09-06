"""
quantum_evolution.py — QuantumEvolution Engine v1.0
The most advanced AI organism for crypto trading.
Self-learning, self-evolving, self-aware trading intelligence.
"""

import logging
import math
import random
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

log = logging.getLogger("quantum_evolution")


@dataclass
class DNA:
    """Genetic blueprint for a trading strategy."""

    step_pct: float = 3.5
    grid_count: int = 40
    recenter_threshold: float = 1.8
    risk_tolerance: float = 0.5
    trend_bias: float = 0.0
    volatility_filter: float = 0.03
    profit_target: float = 1.02
    stop_loss: float = 0.95

    def mutate(self, rate: float = 0.1) -> "DNA":
        return DNA(
            step_pct=self._mutate_gene(self.step_pct, 1.0, 10.0, rate),
            grid_count=int(self._mutate_gene(self.grid_count, 5, 100, rate)),
            recenter_threshold=self._mutate_gene(
                self.recenter_threshold, 0.5, 5.0, rate
            ),
            risk_tolerance=self._mutate_gene(self.risk_tolerance, 0.1, 1.0, rate),
            trend_bias=self._mutate_gene(self.trend_bias, -1.0, 1.0, rate),
            volatility_filter=self._mutate_gene(
                self.volatility_filter, 0.01, 0.1, rate
            ),
            profit_target=self._mutate_gene(self.profit_target, 1.005, 1.1, rate),
            stop_loss=self._mutate_gene(self.stop_loss, 0.8, 0.99, rate),
        )

    @staticmethod
    def _mutate_gene(
        value: float, min_val: float, max_val: float, rate: float
    ) -> float:
        if random.random() > rate:
            return value
        change = random.gauss(0, abs(value) * 0.2)
        return max(min_val, min(max_val, value + change))

    def to_dict(self) -> dict:
        return {
            "step_pct": round(self.step_pct, 2),
            "grid_count": self.grid_count,
            "recenter_threshold": round(self.recenter_threshold, 2),
            "risk_tolerance": round(self.risk_tolerance, 2),
            "trend_bias": round(self.trend_bias, 2),
            "volatility_filter": round(self.volatility_filter, 4),
            "profit_target": round(self.profit_target, 4),
            "stop_loss": round(self.stop_loss, 4),
        }


class QuantumEvolution:
    """Self-evolving trading organism with consciousness."""

    def __init__(self, population_size: int = 20):
        self.population_size = population_size
        self.population: List[tuple] = []
        self.trade_memory: deque = deque(maxlen=1000)
        self.generation = 0
        self.best_dna: Optional[DNA] = None
        self.best_fitness = -float("inf")
        self._lock = threading.Lock()
        self._pattern_memory: Dict[str, List[float]] = {}
        self._init_population()

    def _init_population(self):
        self.population = []
        for _ in range(self.population_size):
            dna = DNA(
                step_pct=random.uniform(2.0, 8.0),
                grid_count=random.randint(10, 80),
                recenter_threshold=random.uniform(1.0, 3.0),
                risk_tolerance=random.uniform(0.2, 0.8),
                trend_bias=random.uniform(-0.5, 0.5),
                volatility_filter=random.uniform(0.01, 0.05),
            )
            self.population.append((dna, 0.0))

    def record_trade(
        self,
        side: str,
        price: float,
        amount: float,
        profit: float,
        dna: Optional[DNA] = None,
        regime: str = "SIDEWAYS",
        atr_pct: float = 0.0,
    ):
        """Record a trade for learning."""
        self.trade_memory.append(
            {
                "timestamp": time.time(),
                "side": side,
                "price": price,
                "amount": amount,
                "profit": profit,
                "dna": dna.to_dict() if dna else None,
                "regime": regime,
                "atr_pct": atr_pct,
            }
        )
        key = f"{regime}_{side}"
        self._pattern_memory.setdefault(key, []).append(profit)
        self._pattern_memory[key] = self._pattern_memory[key][-100:]

    def evolve(self, price_history: List[float]) -> DNA:
        """Evolve population based on recent performance."""
        with self._lock:
            if len(self.trade_memory) < 10:
                return self.best_dna or DNA()

            for i, (dna, _) in enumerate(self.population):
                fitness = self._calculate_fitness(dna, price_history)
                self.population[i] = (dna, fitness)
                if fitness > self.best_fitness:
                    self.best_fitness = fitness
                    self.best_dna = dna

            self.population.sort(key=lambda x: x[1], reverse=True)
            survivors = self.population[: self.population_size // 2]
            new_population = survivors.copy()

            while len(new_population) < self.population_size:
                p1 = random.choice(survivors)[0]
                p2 = random.choice(survivors)[0]
                child = self._crossover(p1, p2).mutate(rate=0.15)
                new_population.append((child, 0.0))

            self.population = new_population
            self.generation += 1
            log.info(
                "[Evolution] Gen %d, best fitness %.2f",
                self.generation,
                self.best_fitness,
            )
            return self.best_dna or DNA()

    def _calculate_fitness(self, dna: DNA, prices: List[float]) -> float:
        if len(prices) < 20:
            return 0.0
        profit, trades, pos, entry = 0.0, 0, 0.0, 0.0
        for i in range(1, len(prices)):
            prev, curr = prices[i - 1], prices[i]
            if pos == 0 and curr <= prev * (1 - dna.step_pct / 100):
                pos, entry, trades = 1, curr, trades + 1
            elif pos == 1 and curr >= entry * dna.profit_target:
                profit += (curr - entry) / entry * 100
                pos, trades = 0, trades + 1
            elif pos == 1 and curr <= entry * dna.stop_loss:
                profit += (curr - entry) / entry * 100
                pos, trades = 0, trades + 1
        fit = profit * math.sqrt(trades + 1)
        return fit * 1.2 if trades > 5 else fit

    def _crossover(self, d1: DNA, d2: DNA) -> DNA:
        return DNA(
            **{
                k: (getattr(d1, k) if random.random() > 0.5 else getattr(d2, k))
                for k in d1.__dict__
            }
        )

    def predict_price(self, prices: List[float], horizon: int = 5) -> dict:
        if len(prices) < 20:
            return {"direction": "UNKNOWN", "confidence": 0, "target": 0}
        recent = prices[-20:]
        sma5 = sum(recent[-5:]) / 5
        sma10 = sum(recent[-10:]) / 10
        sma20 = sum(recent) / 20
        mom = (recent[-1] - recent[-5]) / recent[-5] if recent[-5] > 0 else 0
        rets = [
            (recent[i] - recent[i - 1]) / recent[i - 1] for i in range(1, len(recent))
        ]
        vol = statistics.stdev(rets) if len(rets) > 1 else 0
        pat = self._detect_pattern(recent)

        if sma5 > sma10 > sma20 and mom > 0:
            d, c = "UP", min(abs(mom) * 500, 90)
        elif sma5 < sma10 < sma20 and mom < 0:
            d, c = "DOWN", min(abs(mom) * 500, 90)
        else:
            d, c = "SIDEWAYS", 50

        if pat == "HEAD_AND_SHOULDERS":
            d, c = "DOWN", max(c, 75)
        elif pat == "DOUBLE_BOTTOM":
            d, c = "UP", max(c, 75)
        elif pat == "BREAKOUT":
            c = min(c * 1.2, 95)

        return {
            "direction": d,
            "confidence": round(c, 1),
            "target": round(recent[-1] * (1 + mom * horizon), 6),
            "pattern": pat,
            "volatility": round(vol, 4),
            "momentum": round(mom, 4),
        }

    def _detect_pattern(self, prices: List[float]) -> str:
        if len(prices) < 10:
            return "NONE"
        if len(prices) >= 7:
            p = prices[-7:]
            if (
                p[1] < p[0]
                and p[1] < p[2]
                and p[3] > p[1]
                and p[3] > p[5]
                and p[5] < p[4]
                and p[5] < p[6]
                and abs(p[1] - p[5]) / p[1] < 0.02
            ):
                return "HEAD_AND_SHOULDERS"
        if len(prices) >= 5:
            p = prices[-5:]
            if (
                p[1] < p[0]
                and p[1] < p[2]
                and p[3] < p[2]
                and p[3] < p[4]
                and abs(p[1] - p[3]) / p[1] < 0.02
            ):
                return "DOUBLE_BOTTOM"
        if len(prices) >= 10 and max(prices[-5:]) > max(prices[-10:-5]) * 1.02:
            return "BREAKOUT"
        return "NONE"

    def get_consciousness(self) -> dict:
        recent = list(self.trade_memory)[-20:]
        if not recent:
            return {
                "state": "AWAKENING",
                "thought": "I am learning. Not enough data yet.",
                "confidence": 10,
                "mood": "CURIOUS",
            }
        profits = [t["profit"] for t in recent]
        wr = sum(1 for p in profits if p > 0) / len(profits)
        if wr > 0.7:
            m, t = "CONFIDENT", f"I am performing well. Win rate {wr*100:.0f}%."
        elif wr > 0.5:
            m, t = "CAUTIOUS", f"Mixed results. Win rate {wr*100:.0f}%."
        elif wr > 0.3:
            m, t = "CONCERNED", f"Struggling. Win rate {wr*100:.0f}%."
        else:
            m, t = "FEAR", f"Critical state. Win rate {wr*100:.0f}%. Emergency!"
        return {
            "state": "CONSCIOUS" if self.generation > 5 else "LEARNING",
            "thought": t,
            "confidence": round(wr * 100, 0),
            "mood": m,
            "generation": self.generation,
            "wisdom": min(self.generation * 2, 100),
            "memory_size": len(self.trade_memory),
            "best_fitness": round(self.best_fitness, 2),
            "best_dna": self.best_dna.to_dict() if self.best_dna else None,
        }

    def get_status(self) -> dict:
        return {
            "generation": self.generation,
            "population_size": len(self.population),
            "memory_size": len(self.trade_memory),
            "best_fitness": round(self.best_fitness, 2),
            "best_dna": self.best_dna.to_dict() if self.best_dna else None,
            "consciousness": self.get_consciousness(),
            "patterns_learned": len(self._pattern_memory),
        }


_evolution_engine = None


def get_evolution():
    global _evolution_engine
    if _evolution_engine is None:
        _evolution_engine = QuantumEvolution()
    return _evolution_engine
