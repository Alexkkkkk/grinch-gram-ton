"""Hard risk limits layered on top of grid logic.

The grid strategy decides *what* it wants to trade; this module decides whether
it is still allowed to. It never opens or closes positions on its own - it only
vetoes orders, records realized PnL, and pauses the trader.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core.config import Config


class RiskLimitExceeded(RuntimeError):
    """Order vetoed by a risk limit. Caller should skip the tick, not force it."""


class RiskLimits:
    def __init__(self, state_path: str | None = None):
        self.cfg = Config().RISK
        self.state_path = Path(
            state_path or os.getenv("RISK_STATE_PATH", "risk_state.json")
        )
        self.day = ""
        self.hour = ""
        self.trades_day = 0
        self.trades_hour = 0
        self.sells_day = 0
        self.realized_ton = 0.0
        self.gross_profit_ton = 0.0
        self.gas_ton = 0.0
        self.loss_streak = 0
        self.paused_until = 0.0
        self._load()

    # ── state ────────────────────────────────────────────────────────────────
    def _load(self):
        try:
            for k, v in json.loads(self.state_path.read_text(encoding="utf-8")).items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            # Keep safe defaults when state is missing/corrupt/unreadable.
            pass

    def _save(self):
        try:
            self.state_path.write_text(
                json.dumps(
                    {
                        "day": self.day,
                        "hour": self.hour,
                        "trades_day": self.trades_day,
                        "trades_hour": self.trades_hour,
                        "sells_day": self.sells_day,
                        "realized_ton": self.realized_ton,
                        "gross_profit_ton": self.gross_profit_ton,
                        "gas_ton": self.gas_ton,
                        "loss_streak": self.loss_streak,
                        "paused_until": self.paused_until,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[RiskLimits] failed to save state to {self.state_path}: {exc}")

    def _roll(self):
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        hour = time.strftime("%Y-%m-%dT%H", time.gmtime(now))
        if day != self.day:
            self.day = day
            self.trades_day = 0
            self.sells_day = 0
            self.realized_ton = 0.0
            self.gross_profit_ton = 0.0
            self.gas_ton = 0.0
        if hour != self.hour:
            self.hour = hour
            self.trades_hour = 0
        self._save()

    # ── recording ────────────────────────────────────────────────────────────
    def record_trade(self, side: str, realized_pnl_ton: float, gas_ton: float = 0.0):
        """Record one fill.

        BUY legs realize nothing (the position is still open) but still count
        against the trade caps. Only SELL legs move the PnL / drawdown counters.
        """
        self._roll()
        self.trades_day += 1
        self.trades_hour += 1
        if str(side).upper() != "SELL":
            self._save()
            return

        self.sells_day += 1
        self.realized_ton += float(realized_pnl_ton)
        self.gross_profit_ton += max(float(realized_pnl_ton), 0.0)
        self.gas_ton += float(gas_ton)
        if realized_pnl_ton < 0:
            self.loss_streak += 1
        else:
            self.loss_streak = 0
        if (
            self.cfg.loss_streak_pause > 0
            and self.loss_streak >= self.cfg.loss_streak_pause
        ):
            self.paused_until = time.time() + self.cfg.pause_after_loss_streak_sec
            self.loss_streak = 0
        self._save()

    def record_cycle(
        self, stake_ton: float = 0.0, gross_ton: float = 0.0, gas_ton: float = 0.0
    ):
        """Backward-compatible alias: one closed cycle == one realized SELL."""
        self.record_trade("SELL", float(gross_ton) - float(gas_ton), float(gas_ton))

    # ── gates ────────────────────────────────────────────────────────────────
    def check_before_order(
        self, order_ton: float, expected_net_pct: float, gas_ton: float
    ):
        """Raise RiskLimitExceeded if the order must not be sent."""
        if not self.cfg.enabled:
            return
        self._roll()

        if os.path.exists(self.cfg.kill_switch_file):
            raise RiskLimitExceeded(f"kill switch present: {self.cfg.kill_switch_file}")

        if time.time() < self.paused_until:
            left = self.paused_until - time.time()
            raise RiskLimitExceeded(f"paused after loss streak, {left:.0f}s left")

        equity = self._equity_ton()
        if self.cfg.max_daily_loss_ton > 0 and self.realized_ton <= -abs(
            self.cfg.max_daily_loss_ton
        ):
            raise RiskLimitExceeded(
                f"daily realized loss {self.realized_ton:+.4f} TON exhausted"
            )
        if equity > 0 and self.cfg.max_daily_loss_pct > 0:
            cap = self.cfg.max_daily_loss_pct / 100.0 * equity
            if self.realized_ton <= -abs(cap):
                raise RiskLimitExceeded(
                    f"daily realized loss above {self.cfg.max_daily_loss_pct}% of equity"
                )

        if (
            self.cfg.max_trades_per_day > 0
            and self.trades_day >= self.cfg.max_trades_per_day
        ):
            raise RiskLimitExceeded(
                f"daily trade cap {self.cfg.max_trades_per_day} reached"
            )
        if (
            self.cfg.max_trades_per_hour > 0
            and self.trades_hour >= self.cfg.max_trades_per_hour
        ):
            raise RiskLimitExceeded(
                f"hourly trade cap {self.cfg.max_trades_per_hour} reached"
            )

        if self.cfg.max_position_ton > 0 and order_ton > self.cfg.max_position_ton:
            raise RiskLimitExceeded(
                f"order {order_ton} TON above MAX_POSITION_TON {self.cfg.max_position_ton}"
            )

        if expected_net_pct < self.cfg.min_expected_net_pct:
            raise RiskLimitExceeded(
                f"expected net {expected_net_pct:.3f}% below "
                f"MIN_EXPECTED_NET_PCT {self.cfg.min_expected_net_pct}%"
            )

        expected_gross = order_ton * expected_net_pct / 100.0
        if expected_gross > 0 and self.cfg.max_gas_pct_of_profit > 0:
            share = gas_ton / expected_gross * 100.0
            if share > self.cfg.max_gas_pct_of_profit:
                raise RiskLimitExceeded(
                    f"gas {gas_ton:.4f} TON is {share:.0f}% of profit {expected_gross:.4f} TON"
                )

    def snapshot(self) -> dict:
        self._roll()
        return {
            "day": self.day,
            "trades_day": self.trades_day,
            "trades_hour": self.trades_hour,
            "sells_day": self.sells_day,
            "pnl_today_ton": round(self.realized_ton, 6),
            "gross_ton": round(self.gross_profit_ton, 6),
            "gas_ton": round(self.gas_ton, 6),
            "gas_share_pct": (
                round(self.gas_ton / self.gross_profit_ton * 100, 1)
                if self.gross_profit_ton > 0
                else None
            ),
            "loss_streak": self.loss_streak,
            "paused_sec_left": max(0, int(self.paused_until - time.time())),
        }

    def _equity_ton(self) -> float:
        try:
            from dedust_client import get_shared_balance

            bal = get_shared_balance() or {}
            return float(bal.get("TON", 0) or 0)
        except Exception:
            return 0.0
