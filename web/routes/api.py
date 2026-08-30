"""API blueprint — production REST endpoints with v7 Quantum Intelligence.
ALL v7 data now comes from unified QuantumBrain — no duplicate calculations."""

import sys
import time

from flask import Blueprint, jsonify, request

from core.config import Config
from core.price_feed_real import (
    get_candles_timeframe,
    get_current_price,
    get_history_for_chart,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")
_start_time = time.time()

# ── References to unified components (injected from main.py) ──────────────────
_brain = None
_grid_trader = None


def set_brain(brain):
    global _brain
    _brain = brain


def set_grid_trader(trader):
    global _grid_trader
    _grid_trader = trader


# ═══════════════════════════════════════════════════════════════════════════════
# v7: Quantum Intelligence — UNIFIED source (from QuantumBrain)
# ═══════════════════════════════════════════════════════════════════════════════


def _get_v7_data() -> dict:
    """Get v7 data from unified QuantumBrain. Falls back to basic if brain unavailable."""
    if _brain:
        state = _brain.get_state()
        return {
            "prophet": state.get("prophet", {}),
            "sentiment": state.get("sentiment", {}),
            "swarm": state.get("swarm", {}),
            "optimizer": {
                "recommended_position_size": round(
                    0.15 + (state.get("xai", {}).get("trust_score", 0.5) * 0.25), 2
                ),
                "recommended_leverage": 1,
                "expected_return_24h": round(
                    (
                        (
                            state.get("price", 0)
                            - list(state.get("price_history", [0]))[-7]
                        )
                        / list(state.get("price_history", [1]))[-7]
                        * 100
                        if len(list(state.get("price_history", []))) > 7
                        else 0
                    ),
                    2,
                ),
            },
            "xai": state.get("xai", {}),
        }
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# Core endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/status")
def api_status():
    grid_active = _grid_trader.is_active if _grid_trader else False
    return jsonify(
        {
            "symbol": Config.SYMBOL,
            "mode": "GRID",
            "grid_enabled": Config.GRID.enabled,
            "grid_active": grid_active,
            "demo": Config.DEMO_MODE,
            "uptime_sec": int(time.time() - _start_time),
            "version": "7.1.4-sync",
        }
    )


@api_bp.route("/config")
def api_config():
    return jsonify(
        {
            "symbol": Config.SYMBOL,
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
            "uptime_sec": int(time.time() - _start_time),
            "version": "7.1.4-sync",
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# v7: Quantum Intelligence endpoints — all from unified brain
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/v7/prophet")
def api_v7_prophet():
    return jsonify(_get_v7_data().get("prophet", {}))


@api_bp.route("/v7/sentiment")
def api_v7_sentiment():
    return jsonify(_get_v7_data().get("sentiment", {}))


@api_bp.route("/v7/swarm")
def api_v7_swarm():
    return jsonify(_get_v7_data().get("swarm", {}))


@api_bp.route("/v7/optimizer")
def api_v7_optimizer():
    return jsonify(_get_v7_data().get("optimizer", {}))


@api_bp.route("/v7/xai")
def api_v7_xai():
    return jsonify(_get_v7_data().get("xai", {}))


@api_bp.route("/v7/all")
def api_v7_all():
    """All v7 Quantum Intelligence — from unified brain."""
    if _brain:
        return jsonify(_brain.get_state())
    return jsonify(_get_v7_data())


# ═══════════════════════════════════════════════════════════════════════════════
# History & Charts
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/history")
def api_history():
    hours = request.args.get("hours", 24, type=int)
    data = get_history_for_chart(hours)
    return jsonify(data)


@api_bp.route("/candles")
def api_candles():
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


# ═══════════════════════════════════════════════════════════════════════════════
# Balance — FIXED to use correct function
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/balance")
def api_balance():
    """Wallet balances from shared cache."""
    try:
        from dedust_client import get_shared_balance

        bal = get_shared_balance()
        ton_bal = bal.get("TON", 0)
        usdt_bal = bal.get("USDT", 0)
    except Exception:
        ton_bal = 0
        usdt_bal = 0

    ton_price = get_current_price()
    usdt_price = 1.0

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
                "price": usdt_price,
                "price_ton": round(1.0 / ton_price, 6) if ton_price > 0 else 0.0,
            },
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Grid — SYNCHRONIZED with real GridTrader state
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/grid/status")
def api_grid_status():
    if _grid_trader:
        state = _grid_trader.get_state_dict()
        return jsonify(
            {
                "active": state.get("active", False),
                "center_price": state.get("center_price", 0),
                "step_pct": state.get("step_pct", 0),
                "upper_price": state.get("upper_price", 0),
                "lower_price": state.get("lower_price", 0),
                "sell_levels": len(state.get("sell_levels", [])),
                "buy_levels": len(state.get("buy_levels", [])),
                "total_profit_ton": state.get("total_profit_ton", 0),
                "last_action": state.get("last_action", ""),
            }
        )
    return jsonify(
        {
            "active": False,
            "levels": [],
            "spread_pct": Config.GRID.step_pct,
            "count": 0,
        }
    )


@api_bp.route("/grid/levels")
def api_grid_levels():
    if _grid_trader:
        return jsonify(_grid_trader.get_state_dict())
    return jsonify({"sell_levels": [], "buy_levels": [], "completed_fills": []})


@api_bp.route("/grid/start", methods=["POST"])
def api_grid_start():
    if _grid_trader:
        price = get_current_price()
        _grid_trader.ai_build_grid(price)
        return jsonify({"ok": True, "price": price})
    return jsonify({"ok": False, "error": "Grid trader not initialized"})


@api_bp.route("/grid/stop", methods=["POST"])
def api_grid_stop():
    if _grid_trader:
        _grid_trader.stop_grid()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Grid trader not initialized"})


# ═══════════════════════════════════════════════════════════════════════════════
# Trades
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/trades")
def api_trades():
    if _grid_trader:
        return jsonify(_grid_trader.get_trade_history())
    return jsonify([])


# ═══════════════════════════════════════════════════════════════════════════════
# Quantum Evolution
# ═══════════════════════════════════════════════════════════════════════════════


@api_bp.route("/evolution")
def api_evolution():
    from quantum_evolution import get_evolution

    evo = get_evolution()
    return jsonify(evo.get_status())


@api_bp.route("/consciousness")
def api_consciousness():
    from quantum_evolution import get_evolution

    evo = get_evolution()
    return jsonify(evo.get_consciousness())
