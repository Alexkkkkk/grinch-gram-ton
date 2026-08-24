"""Thread-safe position manager with memory optimization."""
import threading
import time
from typing import Any, Dict, List, Optional


class PositionManager:
    __slots__ = ("_lock", "_trades", "_shorts", "_history", "_max_history")

    def __init__(self, max_history: int = 10000) -> None:
        self._lock = threading.RLock()
        self._trades: List[Dict[str, Any]] = []
        self._shorts: List[Dict[str, Any]] = []
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history

    @property
    def open_trades(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._trades)

    @property
    def open_shorts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._shorts)

    @property
    def all_open(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._trades) + list(self._shorts)

    def add(self, trade: Dict[str, Any], is_short: bool = False) -> None:
        with self._lock:
            if is_short:
                self._shorts.append(trade)
            else:
                self._trades.append(trade)

    def remove(self, trade_id: str, is_short: bool = False) -> Optional[Dict[str, Any]]:
        with self._lock:
            pool = self._shorts if is_short else self._trades
            for i, t in enumerate(pool):
                if t.get("id") == trade_id:
                    return pool.pop(i)
            return None

    def update(self, trade_id: str, is_short: bool = False, **kwargs) -> bool:
        with self._lock:
            pool = self._shorts if is_short else self._trades
            for t in pool:
                if t.get("id") == trade_id:
                    t.update(kwargs)
                    return True
            return False

    def close(self, trade: Dict[str, Any], pnl: float, is_short: bool = False) -> None:
        trade["pnl"] = pnl
        trade["closed_at"] = time.time()
        with self._lock:
            self._history.append(trade)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            self._shorts = [t for t in self._shorts if t.get("id") != trade.get("id")]
            self._trades = [t for t in self._trades if t.get("id") != trade.get("id")]

    def merge_longs(self) -> None:
        with self._lock:
            if len(self._trades) <= 1:
                return
            total_stake = sum(t.get("stake_ton", 0) for t in self._trades)
            total_amount = sum(t.get("amount", 0) for t in self._trades)
            avg_price = sum(t.get("entry_price", 0) * t.get("amount", 0) for t in self._trades) / (total_amount or 1)
            merged = {
                "id": f"merged_{self._trades[0].get('id', '0')}",
                "entry_price": avg_price,
                "amount": total_amount,
                "stake_ton": total_stake,
                "trade_type": "long",
                "merged_count": len(self._trades),
                "opened_at": min((t.get("opened_at", "") for t in self._trades), default=""),
            }
            self._trades = [merged]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            wins = sum(1 for t in self._history if t.get("pnl", 0) > 0)
            total = len(self._history)
            total_pnl = sum(t.get("pnl", 0) for t in self._history)
            return {
                "open_count": len(self._trades),
                "short_count": len(self._shorts),
                "total_closed": total,
                "winning_trades": wins,
                "losing_trades": total - wins,
                "total_pnl": round(total_pnl, 4),
                "win_rate": round(wins / total, 4) if total > 0 else 0.0,
            }

    def clear(self) -> None:
        with self._lock:
            self._trades = []
            self._shorts = []
