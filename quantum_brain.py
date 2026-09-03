"""
quantum_brain.py — Единый мозг QuantumGrinch v7.1
Синхронизирован со всеми компонентами. Единый источник истины для AI.
"""

import logging
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List

from core.config import Config
from kimi_grid_control import KimiGridControl

log = logging.getLogger("quantum_brain")


@dataclass
class BrainState:
    price: float = 0.0
    price_history: deque = field(default_factory=lambda: deque(maxlen=500))
    candles: List[dict] = field(default_factory=list)

    prophet_signal: str = "HOLD"
    prophet_confidence: float = 0.0
    prophet_target: float = 0.0

    sentiment_fg: float = 50.0
    sentiment_label: str = "Neutral"
    sentiment_signal: str = "HOLD"

    swarm_consensus: str = "HOLD"
    swarm_buy_count: int = 0
    swarm_sell_count: int = 0
    swarm_hold_count: int = 16

    xai_trust: float = 0.5
    xai_label: str = "Waiting..."

    regime: str = "SIDEWAYS"
    atr_pct: float = 3.5
    optimal_step: float = field(default_factory=lambda: Config.GRID.step_pct)
    risk_level: int = 0
    trap_detected: bool = False
    trap_confidence: float = 0.0
    pause_buying: bool = False

    unified_signal: str = "HOLD"
    unified_confidence: float = 0.0
    unified_action: str = "WAIT"

    kimi_enabled: bool = False
    kimi_ready: bool = False
    kimi_signal: str = "HOLD"
    kimi_confidence: float = 0.0
    kimi_action: str = "WAIT"
    kimi_step_pct: float = field(default_factory=lambda: Config.GRID.step_pct)
    kimi_investment_ton: float = 0.0
    kimi_ton_per_step: float = 0.0
    kimi_sell_levels: int = field(default_factory=lambda: Config.GRID.sell_levels)
    kimi_buy_levels: int = field(default_factory=lambda: Config.GRID.buy_levels)
    kimi_reason: str = ""
    kimi_last_update: float = 0.0
    kimi_error: str = ""

    last_update: float = 0.0
    update_count: int = 0

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "prophet": {
                "signal": self.prophet_signal,
                "confidence": round(self.prophet_confidence, 1),
                "target": round(self.prophet_target, 6),
            },
            "sentiment": {
                "fear_greed": {
                    "value": round(self.sentiment_fg, 1),
                    "label": self.sentiment_label,
                },
                "signal": self.sentiment_signal,
            },
            "swarm": {
                "consensus": self.swarm_consensus,
                "buy_count": self.swarm_buy_count,
                "sell_count": self.swarm_sell_count,
                "hold_count": self.swarm_hold_count,
            },
            "xai": {
                "trust_score": self.xai_trust,
                "trust_label": self.xai_label,
            },
            "grid_ai": {
                "regime": self.regime,
                "atr_pct": round(self.atr_pct, 2),
                "optimal_step": round(self.optimal_step, 2),
                "risk_level": self.risk_level,
                "trap_detected": self.trap_detected,
                "trap_confidence": round(self.trap_confidence, 1),
                "pause_buying": self.pause_buying,
            },
            "unified": {
                "signal": self.unified_signal,
                "confidence": round(self.unified_confidence, 1),
                "action": self.unified_action,
            },
            "kimi": {
                "enabled": self.kimi_enabled,
                "ready": self.kimi_ready,
                "signal": self.kimi_signal,
                "confidence": round(self.kimi_confidence, 1),
                "action": self.kimi_action,
                "step_pct": round(self.kimi_step_pct, 2),
                "investment_ton": round(self.kimi_investment_ton, 6),
                "ton_per_step": round(self.kimi_ton_per_step, 6),
                "sell_levels": self.kimi_sell_levels,
                "buy_levels": self.kimi_buy_levels,
                "reason": self.kimi_reason,
                "last_update": self.kimi_last_update,
                "error": self.kimi_error,
            },
            # Public Groq alias; keep the historical kimi key for compatibility.
            "groq": {
                "enabled": self.kimi_enabled,
                "ready": self.kimi_ready,
                "signal": self.kimi_signal,
                "confidence": round(self.kimi_confidence, 1),
                "action": self.kimi_action,
                "step_pct": round(self.kimi_step_pct, 2),
                "investment_ton": round(self.kimi_investment_ton, 6),
                "ton_per_step": round(self.kimi_ton_per_step, 6),
                "sell_levels": self.kimi_sell_levels,
                "buy_levels": self.kimi_buy_levels,
                "reason": self.kimi_reason,
                "last_update": self.kimi_last_update,
                "error": self.kimi_error,
            },
            "last_update": self.last_update,
        }


class QuantumBrain:
    def __init__(self):
        self.state = BrainState()
        self._lock = threading.Lock()
        self._grid_trader = None
        self._price_feed = None
        self._running = False
        self._thread = None
        self._fill_history: deque = deque(maxlen=200)
        self._kimi = KimiGridControl()

    def inject(self, grid_trader=None, price_feed=None):
        self._grid_trader = grid_trader
        self._price_feed = price_feed

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="quantum-brain"
        )
        self._thread.start()
        log.info("[QuantumBrain] Started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as e:
                log.error("[QuantumBrain] Tick error: %s", e)
            time.sleep(5)

    def _tick(self):
        self._collect_data()
        self._run_prophet()
        self._run_sentiment()
        self._run_swarm()
        self._run_xai()
        self._run_grid_ai()
        self._run_kimi_control()
        self._unify_decision()
        self._execute_action()
        self.state.last_update = time.time()
        self.state.update_count += 1

    def _collect_data(self):
        price = 0.0
        if self._price_feed:
            try:
                price = self._price_feed()
            except Exception:
                pass
        if price <= 0 and self.state.price_history:
            price = self.state.price_history[-1]
        if price > 0:
            self.state.price = price
            self.state.price_history.append(price)

    def _run_prophet(self):
        prices = list(self.state.price_history)
        if len(prices) < 14:
            return
        current = prices[-1]

        def prophet_signal(horizon):
            if len(prices) < horizon + 1:
                return "HOLD", 0.0
            past = prices[-(horizon + 1) : -1]
            change = (current - past[0]) / past[0] if past[0] > 0 else 0
            if change > 0.005:
                return "BUY", min(abs(change) * 10000, 95)
            elif change < -0.005:
                return "SELL", min(abs(change) * 10000, 95)
            return "HOLD", min(abs(change) * 5000, 40)

        sig_3, conf_3 = prophet_signal(3)
        sig_7, conf_7 = prophet_signal(7)
        sig_14, conf_14 = prophet_signal(14)

        self.state.prophet_confidence = conf_3 * 0.5 + conf_7 * 0.3 + conf_14 * 0.2
        signals = [sig_3, sig_7, sig_14]
        self.state.prophet_signal = max(set(signals), key=signals.count)

        momentum = (
            (current - prices[-7]) / prices[-7]
            if len(prices) >= 7 and prices[-7] > 0
            else 0
        )
        self.state.prophet_target = current * (1 + momentum * 0.5)

    def _run_sentiment(self):
        prices = list(self.state.price_history)
        if len(prices) < 10:
            self.state.sentiment_fg = 50.0
            self.state.sentiment_label = "Neutral"
            self.state.sentiment_signal = "HOLD"
            return

        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))
        ]
        volatility = statistics.stdev(returns[-10:]) if len(returns) >= 10 else 0
        avg_return = sum(returns[-10:]) / 10

        fg = 50 + (avg_return * 5000) - (volatility * 2000)
        fg = max(5, min(95, fg))
        self.state.sentiment_fg = fg

        if fg >= 75:
            self.state.sentiment_label, self.state.sentiment_signal = (
                "Extreme Greed",
                "SELL",
            )
        elif fg >= 55:
            self.state.sentiment_label, self.state.sentiment_signal = "Greed", "HOLD"
        elif fg >= 45:
            self.state.sentiment_label, self.state.sentiment_signal = "Neutral", "HOLD"
        elif fg >= 25:
            self.state.sentiment_label, self.state.sentiment_signal = "Fear", "BUY"
        else:
            self.state.sentiment_label, self.state.sentiment_signal = (
                "Extreme Fear",
                "BUY",
            )

    def _run_swarm(self):
        prices = list(self.state.price_history)
        if len(prices) < 14:
            self.state.swarm_consensus = "HOLD"
            return

        def sma(data, window):
            return (
                sum(data[-window:]) / window
                if len(data) >= window
                else sum(data) / len(data)
            )

        strategies = [
            ("SMA3", lambda p: "BUY" if p[-1] > sma(p, 3) else "SELL"),
            ("SMA5", lambda p: "BUY" if p[-1] > sma(p, 5) else "SELL"),
            ("SMA7", lambda p: "BUY" if p[-1] > sma(p, 7) else "SELL"),
            ("SMA10", lambda p: "BUY" if p[-1] > sma(p, 10) else "SELL"),
            ("MOM3", lambda p: "BUY" if p[-1] > p[-4] else "SELL"),
            ("MOM5", lambda p: "BUY" if p[-1] > p[-6] else "SELL"),
            ("MOM7", lambda p: "BUY" if p[-1] > p[-8] else "SELL"),
            ("TREND", lambda p: "BUY" if p[-1] > sma(p, min(len(p), 14)) else "SELL"),
        ]

        signals = []
        for name, strat in strategies:
            try:
                sig = strat(prices)
            except Exception:
                sig = "HOLD"
            signals.append(sig)

        buy_count = sum(1 for s in signals if s == "BUY")
        sell_count = sum(1 for s in signals if s == "SELL")
        hold_count = len(signals) - buy_count - sell_count

        if buy_count > sell_count and buy_count > hold_count:
            consensus = "BUY"
        elif sell_count > buy_count and sell_count > hold_count:
            consensus = "SELL"
        else:
            consensus = "HOLD"

        self.state.swarm_consensus = consensus
        self.state.swarm_buy_count = buy_count
        self.state.swarm_sell_count = sell_count
        self.state.swarm_hold_count = hold_count

    def _run_xai(self):
        signals = [
            self.state.prophet_signal,
            self.state.sentiment_signal,
            self.state.swarm_consensus,
        ]
        agreement = max(set(signals), key=signals.count)
        agreement_count = signals.count(agreement)

        if agreement_count == 3:
            self.state.xai_trust, self.state.xai_label = (
                0.92,
                "High Confidence — All systems agree",
            )
        elif agreement_count == 2:
            self.state.xai_trust, self.state.xai_label = (
                0.65,
                "Moderate — Minor disagreement detected",
            )
        else:
            self.state.xai_trust, self.state.xai_label = (
                0.28,
                "Low — Conflicting signals, use caution",
            )

    def _run_grid_ai(self):
        prices = list(self.state.price_history)
        if len(prices) < 14:
            self.state.regime = "SIDEWAYS"
            return

        recent = prices[-30:]
        sma7 = sum(recent[-7:]) / 7
        sma14 = sum(recent[-14:]) / 14
        current = recent[-1]
        returns = [
            (recent[i] - recent[i - 1]) / recent[i - 1] for i in range(1, len(recent))
        ]
        vol = sum(r**2 for r in returns) / len(returns) ** 0.5 if returns else 0

        if vol > 0.03:
            if current > sma7 > sma14:
                self.state.regime = "TREND_UP"
            elif current < sma7 < sma14:
                self.state.regime = "TREND_DOWN"
            else:
                self.state.regime = "VOLATILE"
        else:
            if current > sma7 * 1.02:
                self.state.regime = "TREND_UP"
            elif current < sma7 * 0.98:
                self.state.regime = "TREND_DOWN"
            else:
                self.state.regime = "SIDEWAYS"

        # ATR-based optimal step
        if len(prices) >= 5:
            trs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
            atr = (
                sum(trs[-20:]) / len(trs[-20:])
                if len(trs) >= 20
                else sum(trs) / len(trs)
            )
            self.state.atr_pct = (atr / current * 100) if current > 0 else 3.5

        if not Config.GRID.adaptive_step:
            self.state.optimal_step = Config.GRID.step_pct
        else:
            if self.state.atr_pct >= 8:
                self.state.optimal_step = 7.0
            elif self.state.atr_pct >= 5:
                self.state.optimal_step = 5.0
            elif self.state.atr_pct >= 3:
                self.state.optimal_step = 4.0
            else:
                self.state.optimal_step = Config.GRID.step_pct
            self.state.optimal_step = max(
                Config.GRID.min_step_pct,
                min(Config.GRID.max_step_pct, self.state.optimal_step),
            )

        # Trap detection
        if len(self._fill_history) >= 5:
            recent_fills = list(self._fill_history)[-5:]
            losses = sum(1 for f in recent_fills if f.get("profit_ton", 0) < 0)
            self.state.trap_detected = losses >= 3
            self.state.trap_confidence = losses * 20
            self.state.pause_buying = self.state.trap_detected

        # Risk level
        if self.state.atr_pct > 8 or self.state.trap_detected:
            self.state.risk_level = 2
        elif self.state.atr_pct > 5:
            self.state.risk_level = 1
        else:
            self.state.risk_level = 0

    def _run_kimi_control(self):
        info = self._kimi.status()
        self.state.kimi_enabled = bool(info["enabled"])
        self.state.kimi_ready = bool(info["ready"])
        self.state.kimi_error = info.get("last_error", "")
        if len(self.state.price_history) < 14:
            return

        prices = list(self.state.price_history)[-40:]
        returns = [
            round((prices[i] - prices[i - 1]) / prices[i - 1] * 100, 4)
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        wallet = {"available": False, "ton": None, "token": None}
        if self._grid_trader and hasattr(self._grid_trader, "_get_balances"):
            try:
                ton, token = self._grid_trader._get_balances()
                wallet = {
                    "available": ton is not None,
                    "ton": round(float(ton), 6) if ton is not None else None,
                    "token": round(float(token), 6) if token is not None else None,
                    "token_symbol": "USDT" if os.getenv("GRID_SELL_AS_TON", "0").strip() == "1" else "token",
                }
            except Exception:
                wallet = {"available": False, "ton": None, "token": None}

        current_grid = {
            "active": False,
            "step_pct": 0.0,
            "sell_levels": 0,
            "buy_levels": 0,
        }
        if self._grid_trader:
            try:
                grid_state = self._grid_trader.get_state_dict()
                current_grid = {
                    "active": bool(grid_state.get("active")),
                    "step_pct": round(float(grid_state.get("step_pct", 0) or 0), 2),
                    "sell_levels": len(grid_state.get("sell_levels", []) or []),
                    "buy_levels": len(grid_state.get("buy_levels", []) or []),
                }
            except Exception:
                pass

        market = {
            "price": round(self.state.price, 8),
            "recent_prices": [round(p, 8) for p in prices],
            "recent_returns_pct": returns[-20:],
            "wallet": wallet,
            "current_grid": current_grid,
            "defaults": {
                "investment_ton": wallet.get("ton"),
                "sell_levels": Config.GRID.sell_levels,
                "buy_levels": Config.GRID.buy_levels,
            },
            "limits": {
                "min_step_pct": Config.GRID.min_step_pct,
                "max_step_pct": Config.GRID.max_step_pct,
                "max_total_levels": self._kimi.max_total_levels,
                "gas_reserve_ton": round(float(Config.GRID.gas_reserve_ton), 6),
                "fee_pct": round(float(Config.FEES.pct), 6),
                "slippage_pct": round(float(Config.FEES.slippage), 6),
                "estimated_sell_gas_ton": round(float(Config.FEES.sell_gas_ton), 6),
                "estimated_buy_gas_ton": round(float(Config.FEES.buy_gas_ton), 6),
                "gas_per_tx_ton": round(float(self._grid_trader._gas_per_tx()), 6) if self._grid_trader and hasattr(self._grid_trader, "_gas_per_tx") else 0.004,
                "min_profitable_order_ton": round(float(self._grid_trader._min_profitable_order_ton(self.state.optimal_step or Config.GRID.step_pct)), 6) if self._grid_trader and hasattr(self._grid_trader, "_min_profitable_order_ton") else 0.05,
            },
            "local": {
                "prophet_signal": self.state.prophet_signal,
                "prophet_confidence": round(self.state.prophet_confidence, 1),
                "sentiment_signal": self.state.sentiment_signal,
                "sentiment_fg": round(self.state.sentiment_fg, 1),
                "swarm_consensus": self.state.swarm_consensus,
                "regime": self.state.regime,
                "atr_pct": round(self.state.atr_pct, 2),
                "optimal_step": round(self.state.optimal_step, 2),
                "risk_level": self.state.risk_level,
                "trap_detected": self.state.trap_detected,
                "pause_buying": self.state.pause_buying,
            },
        }
        self._kimi.decide(market)
        info = self._kimi.status()
        self.state.kimi_enabled = bool(info["enabled"])
        self.state.kimi_ready = bool(info["ready"])
        self.state.kimi_error = info.get("last_error", "")
        decision = info.get("decision") or {}
        if decision:
            self.state.kimi_signal = decision.get("signal", "HOLD")
            self.state.kimi_confidence = float(decision.get("confidence", 0.0) or 0.0)
            self.state.kimi_action = decision.get("action", "WAIT")
            self.state.kimi_step_pct = float(
                decision.get("step_pct", self.state.optimal_step)
                or self.state.optimal_step
            )
            self.state.kimi_investment_ton = float(
                decision.get("investment_ton", 0.0) or 0.0
            )
            self.state.kimi_ton_per_step = float(
                decision.get("ton_per_step", 0.0) or 0.0
            )
            self.state.kimi_sell_levels = int(
                decision.get("sell_levels", Config.GRID.sell_levels)
                or Config.GRID.sell_levels
            )
            self.state.kimi_buy_levels = int(
                decision.get("buy_levels", Config.GRID.buy_levels)
                or Config.GRID.buy_levels
            )
            self.state.kimi_reason = decision.get("reason", "")
            self.state.kimi_last_update = float(decision.get("updated_at", 0.0) or 0.0)

    def _unify_decision(self):
        signals = [
            self.state.prophet_signal,
            self.state.sentiment_signal,
            self.state.swarm_consensus,
        ]
        agreement = max(set(signals), key=signals.count)
        agreement_count = signals.count(agreement)

        confidence = 0.0
        if agreement_count == 3:
            confidence = max(self.state.prophet_confidence, 60) * 0.9
        elif agreement_count == 2:
            confidence = max(self.state.prophet_confidence, 40) * 0.6
        else:
            confidence = 20.0

        self.state.unified_signal = agreement
        self.state.unified_confidence = confidence

        # Local safety rules always take precedence over the external model.
        if self.state.trap_detected and confidence < 70:
            self.state.unified_action = "STOP"
            return
        if self.state.pause_buying:
            self.state.unified_action = "PAUSE_BUY"
            return

        if self.state.kimi_ready:
            self.state.unified_signal = self.state.kimi_signal
            self.state.unified_confidence = self.state.kimi_confidence
            kimi_action = self.state.kimi_action
            if kimi_action == "STOP":
                self.state.unified_action = "STOP"
            elif kimi_action == "PAUSE_BUY":
                self.state.unified_action = "PAUSE_BUY"
            elif (
                kimi_action in ("BUILD", "START", "REBUILD")
                and self.state.kimi_confidence >= self._kimi.min_confidence
            ):
                self.state.unified_action = kimi_action
            else:
                self.state.unified_action = "WAIT"
            return

        if agreement == "BUY" and confidence > 60 and not self._grid_trader_active():
            self.state.unified_action = "BUILD"
        else:
            self.state.unified_action = "WAIT"

    def _grid_trader_active(self):
        if self._grid_trader and hasattr(self._grid_trader, "is_active"):
            return self._grid_trader.is_active
        return False

    def _execute_action(self):
        """Send unified action to grid trader if connected."""
        if self._grid_trader and hasattr(self._grid_trader, "_update_ai"):
            pass  # Grid trader pulls state via get_state()

    def record_fill(
        self,
        side: str,
        step_used: float,
        atr_pct: float,
        regime: str,
        profit_ton: float = 0,
        profit_pct: float = 0,
    ):
        """Record a grid fill for learning."""
        self._fill_history.append(
            {
                "timestamp": time.time(),
                "side": side,
                "step_used": step_used,
                "atr_pct": atr_pct,
                "regime": regime,
                "profit_ton": profit_ton,
                "profit_pct": profit_pct,
            }
        )

    def kimi_required_for_auto_grid(self) -> bool:
        return bool(self._kimi.required_for_auto_grid and self._kimi.enabled)

    def kimi_allows_initial_build(self) -> bool:
        return bool(
            self.state.kimi_ready
            and self.state.kimi_action in ("BUILD", "START")
            and self.state.kimi_confidence >= self._kimi.min_confidence
        )

    def get_state(self) -> dict:
        """Get full brain state (thread-safe copy)."""
        with self._lock:
            return self.state.to_dict()

    def get_v7_data(self) -> dict:
        """Get v7-formatted data for API."""
        return self.get_state()


_brain_instance = None


def get_brain():
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = QuantumBrain()
    return _brain_instance
