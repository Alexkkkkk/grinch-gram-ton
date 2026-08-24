"""API blueprint — production REST endpoints."""
import time
from flask import Blueprint, jsonify, request

from core.config import Config

api_bp = Blueprint("api", __name__, url_prefix="/api")

_start_time = time.time()


@api_bp.route("/status")
def api_status():
    return jsonify({
        "symbol": Config.SYMBOL,
        "mode": Config.TRADE_MODE,
        "grid_enabled": Config.GRID.enabled,
        "demo": Config.DEMO_MODE,
        "uptime_sec": int(time.time() - _start_time),
    })


@api_bp.route("/config")
def api_config():
    return jsonify({
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
    })


@api_bp.route("/metrics")
def api_metrics():
    """Basic metrics for monitoring."""
    return jsonify({
        "uptime_sec": int(time.time() - _start_time),
        "version": "2.1.0",
        "python_version": "3.11",
    })


@api_bp.route("/trades")
def api_trades():
    try:
        import db_store
        trades = db_store.trades_get_recent(50) if hasattr(db_store, 'is_available') and db_store.is_available() else []
    except Exception:
        trades = []
    return jsonify({"trades": trades, "count": len(trades)})
