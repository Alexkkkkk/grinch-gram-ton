"""
quantum_optimizer.py v1 — QuantumGrid Optimizer.

Симуляция квантовой оптимизации для поиска лучших параметров сетки:
  1. QuantumState      — суперпозиция параметров (шаг, уровни, TP)
  2. QuantumAnnealer   — квантовый отжиг с туннелированием
  3. EnergyLandscape   — функция энергии = ожидаемая прибыль сетки
  4. ParallelUniverses — параллельный поиск в нескольких "вселенных"

Идея: вместо жадного поиска — "квантовое" исследование пространства
гиперпараметров с возможностью "туннелировать" через локальные минимумы.
"""

import logging
import math
import random
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("quantum_optimizer")

# ── Константы ────────────────────────────────────────────────────────────────
QUANTUM_TEMP_START = 10.0  # начальная температура
QUANTUM_TEMP_END = 0.01  # конечная температура
QUANTUM_TUNNEL_PROB = 0.15  # вероятность квантового туннелирования
N_UNIVERSES = 8  # параллельных вселенных
N_ITERATIONS = 200  # итераций на вселенную
PARAM_BOUNDS = {
    "step_pct": (2.0, 12.0),
    "grid_levels": (10, 60),
    "take_profit_pct": (3.0, 20.0),
    "trailing_stop_pct": (2.0, 15.0),
    "min_order_usdt": (5.0, 100.0),
}


@dataclass
class QuantumState:
    """Состояние сетки в "суперпозиции" — набор параметров."""

    step_pct: float
    grid_levels: int
    take_profit_pct: float
    trailing_stop_pct: float
    min_order_usdt: float
    energy: float = float("inf")
    fitness: float = 0.0

    def to_dict(self) -> dict:
        return {
            "step_pct": round(self.step_pct, 4),
            "grid_levels": self.grid_levels,
            "take_profit_pct": round(self.take_profit_pct, 4),
            "trailing_stop_pct": round(self.trailing_stop_pct, 4),
            "min_order_usdt": round(self.min_order_usdt, 4),
            "energy": round(self.energy, 6),
            "fitness": round(self.fitness, 6),
        }

    @classmethod
    def random_state(cls, rng: random.Random = None) -> "QuantumState":
        r = rng or random.Random()
        return cls(
            step_pct=r.uniform(*PARAM_BOUNDS["step_pct"]),
            grid_levels=r.randint(*PARAM_BOUNDS["grid_levels"]),
            take_profit_pct=r.uniform(*PARAM_BOUNDS["take_profit_pct"]),
            trailing_stop_pct=r.uniform(*PARAM_BOUNDS["trailing_stop_pct"]),
            min_order_usdt=r.uniform(*PARAM_BOUNDS["min_order_usdt"]),
        )

    def copy(self) -> "QuantumState":
        return QuantumState(
            step_pct=self.step_pct,
            grid_levels=self.grid_levels,
            take_profit_pct=self.take_profit_pct,
            trailing_stop_pct=self.trailing_stop_pct,
            min_order_usdt=self.min_order_usdt,
            energy=self.energy,
            fitness=self.fitness,
        )


class EnergyLandscape:
    """
    Функция энергии = отрицательная ожидаемая прибыль сетки.
    Чем ниже энергия → тем лучше параметры.
    """

    def __init__(self, candles: List[dict], fee_pct: float = 0.0025):
        self._candles = candles
        self._fee_pct = fee_pct
        self._prices = np.array([float(c.get("close", c.get("c", 0))) for c in candles])
        self._volumes = np.array(
            [float(c.get("volume", c.get("v", 0))) for c in candles]
        )

    def _simulate_grid(self, state: QuantumState) -> dict:
        """
        Быстрая симуляция сетки на исторических данных.
        Возвращает метрики: profit, max_dd, win_rate, sharpe.
        """
        if len(self._prices) < 50:
            return {"profit": -999, "max_dd": 1.0, "win_rate": 0.0, "sharpe": -999}

        prices = self._prices
        n = len(prices)
        center = prices[0]
        step = state.step_pct / 100.0

        # Создаём уровни
        buy_levels = [center * (1 - step * (i + 1)) for i in range(state.grid_levels)]
        sell_levels = [center * (1 + step * (i + 1)) for i in range(state.grid_levels)]

        # Симуляция
        capital = 1000.0  # USDT
        grinch_held = 0.0
        trades = []
        peak = capital
        max_dd = 0.0

        for i in range(1, n):
            price = prices[i]
            # Проверяем покупки
            for bl in buy_levels:
                if price <= bl and capital >= state.min_order_usdt:
                    amount = state.min_order_usdt / price
                    grinch_held += amount * (1 - self._fee_pct)
                    capital -= state.min_order_usdt
                    trades.append({"side": "buy", "price": price, "amount": amount})
                    buy_levels.remove(bl)
                    break

            # Проверяем продажи
            for sl in sell_levels:
                if price >= sl and grinch_held > 0:
                    value = grinch_held * price * (1 - self._fee_pct)
                    profit = value - sum(
                        t["amount"] * t["price"] for t in trades if t["side"] == "buy"
                    )
                    capital += value
                    grinch_held = 0.0
                    trades = []
                    sell_levels.remove(sl)
                    break

            # Пересчёт уровней при сильном отклонении
            if abs(price - center) / center > state.step_pct / 100 * 3:
                center = price
                buy_levels = [
                    center * (1 - step * (i + 1)) for i in range(state.grid_levels)
                ]
                sell_levels = [
                    center * (1 + step * (i + 1)) for i in range(state.grid_levels)
                ]

            total = capital + grinch_held * price
            peak = max(peak, total)
            dd = (peak - total) / peak
            max_dd = max(max_dd, dd)

        final_value = capital + grinch_held * prices[-1]
        profit = (final_value - 1000.0) / 1000.0 * 100

        win_rate = 0.5
        if trades:
            # Прокси: если цена выше средней покупки → win
            avg_buy = sum(t["price"] for t in trades if t["side"] == "buy") / max(
                1, sum(1 for t in trades if t["side"] == "buy")
            )
            win_rate = 1.0 if prices[-1] > avg_buy else 0.0

        # Sharpe-like: profit / max_dd
        sharpe = profit / (max_dd * 100 + 1e-9) if max_dd > 0 else profit

        return {
            "profit": profit,
            "max_dd": max_dd * 100,
            "win_rate": win_rate,
            "sharpe": sharpe,
        }

    def evaluate(self, state: QuantumState) -> float:
        """
        Вычислить энергию (ниже = лучше).
        Комбинированная метрика: profit, drawdown, win_rate.
        """
        sim = self._simulate_grid(state)
        profit = sim["profit"]
        max_dd = sim["max_dd"]
        win_rate = sim["win_rate"]
        sharpe = sim["sharpe"]

        # Энергия = отрицательная прибыль + штраф за просадку + штраф за низкий win_rate
        energy = (
            -profit * 2.0  # максимизируем прибыль
            + max_dd * 5.0  # минимизируем просадку
            - win_rate * 10.0  # максимизируем win_rate
            - sharpe * 3.0  # максимизируем Sharpe
            + (state.grid_levels - 30) ** 2
            * 0.01  # штраф за экстремальное число уровней
        )
        state.energy = energy
        state.fitness = profit
        return energy


class QuantumAnnealer:
    """
    Квантовый отжиг: исследуем пространство параметров с "туннелированием".
    """

    def __init__(self, landscape: EnergyLandscape, seed: int = None):
        self._landscape = landscape
        self._rng = random.Random(seed)
        self._best_state: Optional[QuantumState] = None
        self._best_energy = float("inf")
        self._history: List[Tuple[float, float]] = []

    def _neighbor(self, state: QuantumState, temp: float) -> QuantumState:
        """Создать соседнее состояние с амплитудой, зависящей от температуры."""
        n = state.copy()
        # Амплитуда мутации уменьшается с температурой
        amp = max(0.1, temp / QUANTUM_TEMP_START)

        if self._rng.random() < 0.3:
            n.step_pct = max(
                PARAM_BOUNDS["step_pct"][0],
                min(
                    PARAM_BOUNDS["step_pct"][1],
                    n.step_pct + self._rng.gauss(0, amp * 2),
                ),
            )
        if self._rng.random() < 0.2:
            n.grid_levels = max(
                PARAM_BOUNDS["grid_levels"][0],
                min(
                    PARAM_BOUNDS["grid_levels"][1],
                    n.grid_levels + self._rng.randint(-3, 3),
                ),
            )
        if self._rng.random() < 0.3:
            n.take_profit_pct = max(
                PARAM_BOUNDS["take_profit_pct"][0],
                min(
                    PARAM_BOUNDS["take_profit_pct"][1],
                    n.take_profit_pct + self._rng.gauss(0, amp * 3),
                ),
            )
        if self._rng.random() < 0.2:
            n.trailing_stop_pct = max(
                PARAM_BOUNDS["trailing_stop_pct"][0],
                min(
                    PARAM_BOUNDS["trailing_stop_pct"][1],
                    n.trailing_stop_pct + self._rng.gauss(0, amp * 2),
                ),
            )

        return n

    def _quantum_tunnel(self, state: QuantumState) -> QuantumState:
        """Квантовое туннелирование: резкий скачок в случайную точку."""
        if self._rng.random() < QUANTUM_TUNNEL_PROB:
            return QuantumState.random_state(self._rng)
        return state

    def _acceptance_prob(self, e_old: float, e_new: float, temp: float) -> float:
        """Вероятность принятия худшего состояния (Metropolis criterion)."""
        if e_new < e_old:
            return 1.0
        return math.exp(-(e_new - e_old) / temp)

    def run(self, n_iterations: int = N_ITERATIONS) -> QuantumState:
        """Запустить квантовый отжиг."""
        current = QuantumState.random_state(self._rng)
        self._landscape.evaluate(current)
        self._best_state = current.copy()
        self._best_energy = current.energy

        for i in range(n_iterations):
            # Температура убывает
            progress = i / n_iterations
            temp = (
                QUANTUM_TEMP_START * (QUANTUM_TEMP_END / QUANTUM_TEMP_START) ** progress
            )

            # Квантовое туннелирование
            candidate = self._quantum_tunnel(current)
            if candidate is not current:
                self._landscape.evaluate(candidate)
            else:
                # Обычная мутация
                candidate = self._neighbor(current, temp)
                self._landscape.evaluate(candidate)

            # Принимаем или отклоняем
            if (
                self._acceptance_prob(current.energy, candidate.energy, temp)
                > self._rng.random()
            ):
                current = candidate

            # Обновляем лучшее
            if current.energy < self._best_energy:
                self._best_state = current.copy()
                self._best_energy = current.energy

            self._history.append((temp, current.energy))

        logger.info(
            "[QuantumAnnealer] Best energy=%.2f fitness=%.2f step=%.2f levels=%d",
            self._best_energy,
            self._best_state.fitness,
            self._best_state.step_pct,
            self._best_state.grid_levels,
        )
        return self._best_state


class ParallelUniverses:
    """
    Параллельный поиск в N "вселенных" с разными сидами.
    Возвращает лучшее состояние из всех вселенных.
    """

    def __init__(self, candles: List[dict], n_universes: int = N_UNIVERSES):
        self._candles = candles
        self._n_universes = n_universes
        self._results: List[QuantumState] = []

    def run(self) -> Tuple[QuantumState, List[QuantumState]]:
        """
        Запустить параллельный поиск.
        Возвращает (best_state, all_states).
        """
        landscape = EnergyLandscape(self._candles)
        universes = []

        for u in range(self._n_universes):
            annealer = QuantumAnnealer(landscape, seed=u * 1000 + int(time.time()))
            state = annealer.run(n_iterations=N_ITERATIONS)
            universes.append(state)

        # Выбираем лучшее
        best = min(universes, key=lambda s: s.energy)
        self._results = universes

        logger.info(
            "[ParallelUniverses] %d universes → best energy=%.2f fitness=%.2f",
            self._n_universes,
            best.energy,
            best.fitness,
        )
        return best, universes

    def get_diversity_report(self) -> dict:
        """Отчёт о разнообразии решений."""
        if not self._results:
            return {}
        energies = [s.energy for s in self._results]
        fitnesses = [s.fitness for s in self._results]
        return {
            "universes": len(self._results),
            "energy_mean": round(np.mean(energies), 4),
            "energy_std": round(np.std(energies), 4),
            "fitness_mean": round(np.mean(fitnesses), 4),
            "fitness_best": round(max(fitnesses), 4),
            "fitness_worst": round(min(fitnesses), 4),
            "convergence": round(np.std(energies) / (abs(np.mean(energies)) + 1e-9), 4),
        }


class QuantumOptimizer:
    """Единый API для квантовой оптимизации."""

    def __init__(self):
        self._last_result: Optional[QuantumState] = None
        self._last_run = 0.0
        self._cooldown = 3600  # не чаще раза в час
        self._lock = threading.RLock()

    def optimize(
        self, candles: List[dict], force: bool = False
    ) -> Optional[QuantumState]:
        """Оптимизировать параметры сетки."""
        with self._lock:
            now = time.time()
            if not force and now - self._last_run < self._cooldown:
                return self._last_result

            if len(candles) < 100:
                logger.warning(
                    "[QuantumOptimizer] Недостаточно данных: %d < 100", len(candles)
                )
                return None

            logger.info(
                "[QuantumOptimizer] Запуск квантовой оптимизации на %d свечах...",
                len(candles),
            )
            parallel = ParallelUniverses(candles, n_universes=N_UNIVERSES)
            best, all_states = parallel.run()

            self._last_result = best
            self._last_run = now

            report = parallel.get_diversity_report()
            logger.info("[QuantumOptimizer] Diversity: %s", report)

            return best

    def get_recommended_params(self, candles: List[dict]) -> dict:
        """Получить рекомендованные параметры (с кешем)."""
        state = self.optimize(candles)
        if state is None:
            return {
                "step_pct": 3.5,
                "grid_levels": 20,
                "take_profit_pct": 6.0,
                "trailing_stop_pct": 3.0,
                "min_order_usdt": 15.0,
                "optimized": False,
            }
        return {
            **state.to_dict(),
            "optimized": True,
            "timestamp": self._last_run,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════
_optimizer: Optional[QuantumOptimizer] = None


def get_optimizer() -> QuantumOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = QuantumOptimizer()
    return _optimizer


def optimize_grid(candles: List[dict], force: bool = False) -> Optional[dict]:
    """Публичный API: оптимизировать параметры сетки."""
    opt = get_optimizer()
    state = opt.optimize(candles, force)
    if state:
        return state.to_dict()
    return None


def get_recommended_params(candles: List[dict]) -> dict:
    """Публичный API: получить рекомендованные параметры."""
    opt = get_optimizer()
    return opt.get_recommended_params(candles)
