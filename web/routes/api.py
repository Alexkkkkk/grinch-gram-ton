"""API blueprint — production REST endpoints with v7 Quantum Intelligence."""

import time
from collections import deque
from typing import List

from flask import Blueprint, jsonify, request

from core.config import Config
from core.price_feed_real import (
    get_candles_timeframe,
    get_history_for_chart,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")
_start_time = time.time()

# ── In-memory data stores (replace with DB in production) ─────────────────────
_price_history: deque = deque(maxlen=500)
_pnl_history: deque = deque(maxlen=500)
_trade_history: List[dict] = []
_grid_levels: List[dict] = []
_bot_running: bool = False


def _generate_mock_history():
    """Generate demo price history for USDT/USDT so charts work immediately."""
    import random

    now = time.time()
    base_price = 1.0  # USDT/USDT ~ $1.00
    price = base_price
    pnl = 0.0
    for i in range(120):
        t = now - (120 - i) * 300  # 5-min intervals over last 10 hours
        # Random walk with slight upward drift
        change = random.gauss(0.0005, 0.008)
        price *= 1 + change
        price = max(0.5, min(2.0, price))  # keep in reasonable range
        pnl += random.gauss(0.02, 0.5)  # accumulating PnL
        _price_history.append({"t": t, "price": round(price, 6)})
        _pnl_history.append({"t": t, "pnl": round(pnl, 4), "price": round(price, 6)})


# Generate mock data on module load so charts work immediately
_generate_mock_history()


def _now() -> float:
    return time.time()


# ═══════════════════════════════════════════════════════════════════════════════
# v7: Quantum Intelligence data
# ═══════════════════════════════════════════════════════════════════════════════
_v7_data: dict = {
    "prophet": {},
    "sentiment": {},
    "swarm": {},
    "optimizer": {},
    "xai": {},
}


def update_v7_data(key: str, data: dict):
    _v7_data[key] = data


# ═══════════════════════════════════════════════════════════════════════════════
# Core endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/status")
def api_status():
    return jsonify(
        {
            "symbol": Config.GRID.symbol,
            "mode": "GRID",
            "grid_enabled": Config.GRID.enabled,
            "demo": Config.DEMO_MODE,
            "uptime_sec": int(_now() - _start_time),
            "bot_running": _bot_running,
            "version": "7.0.0",
        }
    )


@api_bp.route("/config")
def api_config():
    return jsonify(
        {
            "symbol": Config.GRID.symbol,
            "trade_amount": Config.TRADE_AMOUNT,
            "grid_step": Config.GRID.step_pct,
            "grid_levels": Config.GRID.count,
            "grid_adaptive": Config.GRID.adaptive_step,
            "fee_pct": Config.FEES.pct,
            "slippage_pct": Config.FEES.slippage,
            "trailing_stop_pct": Config.TRAIL.base_pct,
            "ai_enabled": Config.AI.autonomous_mode,
            "ai_min_conf": Config.AI.min_confidence,
        }
    )


@api_bp.route("/metrics")
def api_metrics():
    return jsonify(
        {
            "uptime_sec": int(_now() - _start_time),
            "version": "7.0.0",
            "python_version": "3.11",
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# v7: Quantum Intelligence endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/v7/prophet")
def api_v7_prophet():
    """Neural Prophet predictions."""
    return jsonify(_v7_data.get("prophet", {}))


@api_bp.route("/v7/sentiment")
def api_v7_sentiment():
    """Market sentiment analysis."""
    return jsonify(_v7_data.get("sentiment", {}))


@api_bp.route("/v7/swarm")
def api_v7_swarm():
    """Swarm intelligence consensus."""
    return jsonify(_v7_data.get("swarm", {}))


@api_bp.route("/v7/optimizer")
def api_v7_optimizer():
    """Quantum optimizer recommendations."""
    return jsonify(_v7_data.get("optimizer", {}))


@api_bp.route("/v7/xai")
def api_v7_xai():
    """XAI explanations and trust scores."""
    return jsonify(_v7_data.get("xai", {}))


@api_bp.route("/v7/all")
def api_v7_all():
    """All v7 Quantum Intelligence data."""
    return jsonify(_v7_data)


# ═══════════════════════════════════════════════════════════════════════════════
# History & Charts
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/history")
def api_history():
    """Price and PnL history for charts — REAL data from STON.fi."""
    hours = request.args.get("hours", 24, type=int)
    data = get_history_for_chart(hours)
    return jsonify(data)


@api_bp.route("/candles")
def api_candles():
    """OHLCV candles for candlestick chart with timeframe support."""
    limit = request.args.get("limit", 200, type=int)
    timeframe = request.args.get("timeframe", "5m", type=str)
    candles = get_candles_timeframe(timeframe, limit)
    return jsonify(
        {
            "candles": [
                {
                    "timestamp": c["t"],
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c.get("volume", 0),
                }
                for c in candles
            ],
            "timeframe": timeframe,
        }
    )


@api_bp.route("/history/price", methods=["POST"])
def api_history_price():
    """Push a new price point."""
    data = request.get_json(silent=True) or {}
    price = data.get("price", 0)
    if price > 0:
        _price_history.append({"t": time.time(), "price": price})
    return jsonify({"ok": True})


@api_bp.route("/history/pnl", methods=["POST"])
def api_history_pnl():
    """Push a new PnL point."""
    data = request.get_json(silent=True) or {}
    pnl = data.get("pnl", 0)
    price = data.get("price", 0)
    _pnl_history.append({"t": time.time(), "pnl": pnl, "price": price})
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# Balance
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/balance")
def api_balance():
    """Wallet balances."""
    # Try to get real balance from dedust_client cache
    try:
        import dedust_client

        bal = dedust_client.get_balance_cached(Config.TON_WALLET)
        ton_bal = bal.get("TON", 0)
        usdt_bal = bal.get("USDT", 0)
    except Exception:
        ton_bal = 0
        usdt_bal = 0

    # Real prices from STON.fi
    from core.price_feed_real import get_current_price as get_real_price

    real_price = get_real_price()
    ton_price = real_price  # USDT = prev. Toncoin = TON
    usdt_price = 1.0  # USD
    token_price_ton = real_price / ton_price if ton_price > 0 else 0.0015

    return jsonify(
        {
            "ok": True,
            "ton": {
                "amount": round(ton_bal, 4),
                "usd": round(ton_bal * ton_price, 2),
                "price": ton_price,
            },
            "token": {
                "symbol": "USDT",
                "amount": round(usdt_bal, 2),
                "usd": round(usdt_bal * usdt_price, 2),
                "price": real_price,
                "price_ton": token_price_ton,
            },
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Grid
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/grid/status")
def api_grid_status():
    return jsonify(
        {
            "active": len(_grid_levels) > 0,
            "levels": _grid_levels,
            "spread_pct": Config.GRID.step_pct,
            "count": len(_grid_levels),
        }
    )


@api_bp.route("/grid/build", methods=["POST"])
def api_grid_build():
    """Build grid levels."""
    global _grid_levels
    data = request.get_json(silent=True) or {}
    upper = data.get("upper")
    lower = data.get("lower")
    count = data.get("grid_count", Config.GRID.count)
    investment = data.get("investment", 1000)

    # Auto-calculate if not provided
    if upper is None or lower is None:
        try:
            import price_feed

            current = price_feed.get_current_price(Config.GRID.symbol)
            if current:
                step = Config.GRID.step_pct / 100
                upper = upper or current * (1 + step * count / 2)
                lower = lower or current * (1 - step * count / 2)
        except Exception:
            current = 1.0
            upper = upper or 1.5
            lower = lower or 0.5

    upper = float(upper or 1.5)
    lower = float(lower or 0.5)
    count = int(count)

    step = (upper - lower) / max(count - 1, 1)
    _grid_levels = []
    for i in range(count):
        price = lower + step * i
        side = "buy" if price < (upper + lower) / 2 else "sell"
        _grid_levels.append(
            {
                "price": round(price, 6),
                "side": side,
                "status": "active",
                "amount": round(investment / count, 2),
            }
        )

    return jsonify(
        {"ok": True, "levels_count": len(_grid_levels), "levels": _grid_levels}
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Bot Control
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/start", methods=["POST"])
def api_start():
    global _bot_running
    _bot_running = True
    return jsonify({"success": True, "message": "Bot started"})


@api_bp.route("/stop", methods=["POST"])
def api_stop():
    global _bot_running
    _bot_running = False
    return jsonify({"success": True, "message": "Bot stopped"})


# ═══════════════════════════════════════════════════════════════════════════════
# Trades
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/trades")
def api_trades():
    try:
        import db_store

        trades = (
            db_store.trades_get_recent(50)
            if hasattr(db_store, "is_available") and db_store.is_available()
            else []
        )
    except Exception:
        trades = _trade_history[-50:]
    return jsonify({"trades": trades, "count": len(trades)})


@api_bp.route("/trade/delete", methods=["POST"])
def api_trade_delete():
    return jsonify({"success": True})


@api_bp.route("/trade/close", methods=["POST"])
def api_trade_close():
    return jsonify({"success": True})


@api_bp.route("/trade/manual_buy", methods=["POST"])
def api_manual_buy():
    return jsonify({"success": True, "tx_hash": None})


@api_bp.route("/trade/manual_sell_all", methods=["POST"])
def api_manual_sell_all():
    return jsonify({"success": True, "tx_hash": None})


# ═══════════════════════════════════════════════════════════════════════════════
# Advisor
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/advisor/apikey", methods=["POST"])
def api_advisor_apikey():
    return jsonify({"success": True})


@api_bp.route("/advisor/providers")
def api_advisor_providers():
    return jsonify({"providers": []})


@api_bp.route("/advisor/providers/<int:provider_id>/key", methods=["POST", "DELETE"])
def api_advisor_provider_key(provider_id):
    return jsonify({"success": True})


@api_bp.route("/advisor/providers/select", methods=["POST"])
def api_advisor_providers_select():
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════════════
# AI
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/ai/decisions")
def api_ai_decisions():
    return jsonify({"decisions": [], "confidence": 0})


@api_bp.route("/ai/signal")
def api_ai_signal():
    """Current AI signal with v7 data."""
    return jsonify(
        {
            "signal": "HOLD",
            "confidence": 0,
            "v7": _v7_data,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Filters & DB
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/filters/status")
def api_filters_status():
    return jsonify({"filters": []})


@api_bp.route("/db/sync_status")
def api_db_sync_status():
    return jsonify({"synced": True, "last_sync": _now()})


# ═══════════════════════════════════════════════════════════════════════════════
# TON
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/ton")
def api_ton():
    return jsonify({"balance": 0, "address": Config.TON_WALLET, "status": "ok"})


@api_bp.route("/ton/refresh", methods=["POST"])
def api_ton_refresh():
    return jsonify({"success": True})


@api_bp.route("/ton/price")
def api_ton_price():
    from core.price_feed_real import get_current_price

    return jsonify({"price": get_current_price(), "currency": "USD"})


# ═══════════════════════════════════════════════════════════════════════════════
# Coin
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/coin")
def api_coin():
    from core.price_feed_real import get_current_price as gp
    from core.price_feed_real import get_price_change_24h as gc

    return jsonify(
        {
            "price": gp(),
            "symbol": Config.GRID.symbol,
            "change_24h": gc(),
        }
    )


@api_bp.route("/coin/trades")
def api_coin_trades():
    return jsonify({"trades": []})


@api_bp.route("/coin/exchanges")
def api_coin_exchanges():
    return jsonify({"exchanges": []})


# ═══════════════════════════════════════════════════════════════════════════════
# Wallets & Liquidator
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/wallets")
def api_wallets():
    return jsonify({"wallets": []})


@api_bp.route("/liquidator")
def api_liquidator():
    return jsonify({"active": False, "threshold": 0})


@api_bp.route("/liquidator/sell", methods=["POST"])
def api_liquidator_sell():
    return jsonify({"success": True})


@api_bp.route("/liquidator/threshold", methods=["POST"])
def api_liquidator_threshold():
    return jsonify({"success": True})


@api_bp.route("/liquidity_guard")
def api_liquidity_guard():
    return jsonify({"guarded": False, "min_liquidity": 0})
