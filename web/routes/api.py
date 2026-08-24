"""API blueprint — all REST endpoints."""
from flask import Blueprint, jsonify, request

from core.config import Config

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/status")
def api_status():
    return jsonify({
        "symbol": Config.SYMBOL,
        "mode": Config.TRADE_MODE,
        "grid_enabled": Config.GRID.enabled,
        "demo": Config.DEMO_MODE,
    })


@api_bp.route("/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify({
            "symbol": Config.SYMBOL,
            "trade_amount": Config.TRADE_AMOUNT,
            "grid_step": Config.GRID.step_pct,
            "grid_levels": Config.GRID.count,
            "fee_pct": Config.FEES.pct,
        })
    data = request.get_json(silent=True) or {}
    # TODO: validate and apply
    return jsonify({"ok": True, "applied": list(data.keys())})


@api_bp.route("/trades")
def api_trades():
    try:
        import db_store
        trades = db_store.trades_get_recent(50) if db_store.is_available() else []
    except Exception:
        trades = []
    return jsonify({"trades": trades})
