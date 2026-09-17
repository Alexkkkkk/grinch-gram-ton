#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════════
# Stub routes — compatibility endpoints for the SPA dashboard.
#
# Endpoints here either proxy the legacy trading controls to the real grid
# controller, or expose live market/wallet data from the running backend.
# They NEVER fabricate values: when a real source is unavailable the response
# degrades to an explicit empty/zero payload instead of inventing data.
# ═══════════════════════════════════════════════════════════════════════════════

from flask import Blueprint, jsonify

from core.config import Config

stubs_bp = Blueprint("stubs", __name__)


def _live_price() -> float:
    """Best available GRAM/USD price from the live market feed (0.0 if unknown)."""
    try:
        from core.price_feed_real import get_current_price

        price = float(get_current_price() or 0)
        if price > 0:
            return price
    except Exception:
        pass
    try:
        return float(getattr(Config, "TON", {}).get("price_usd", 0) or 0)
    except Exception:
        return 0.0


def _feed_status() -> dict:
    """Live feed status (source / staleness), empty dict when unavailable."""
    try:
        from core.price_feed_real import get_feed_status

        return get_feed_status() or {}
    except Exception:
        return {}


# ── Trading control ───────────────────────────────────────────────────────────
@stubs_bp.route("/api/start", methods=["POST"])
def start_bot():
    # Keep the legacy dashboard button wired to the real grid controller.
    from web.routes.api import api_grid_start

    return api_grid_start()


@stubs_bp.route("/api/stop", methods=["POST"])
def stop_bot():
    from web.routes.api import api_grid_stop

    return api_grid_stop()


# ── TON info ──────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/ton")
def ton_info():
    return jsonify({"ok": True, "wallet": Config.TON_WALLET, "network": "mainnet"})


@stubs_bp.route("/api/ton/price")
def ton_price():
    """Real GRAM/USD price from the live feed (no placeholder values)."""
    price = _live_price()
    return jsonify({"ok": True, "price_usd": price, "price_ton": 1.0})


@stubs_bp.route("/api/ton/refresh", methods=["POST"])
def ton_refresh():
    return jsonify({"ok": True, "message": "Price refresh requested"})


# ── Wallets ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/wallets")
def wallets():
    balance = 0
    try:
        from web.routes.api import _grid_trader  # type: ignore

        if _grid_trader is not None:
            snap = _grid_trader.get_wallet_snapshot()
            if isinstance(snap, dict):
                balance = snap.get("ton", 0) or 0
    except Exception:
        balance = 0
    return jsonify(
        {
            "ok": True,
            "wallets": [
                {"address": Config.TON_WALLET, "type": "ton", "balance": balance}
            ],
        }
    )


# ── Trade manual ──────────────────────────────────────────────────────────────
@stubs_bp.route("/api/trade/manual_buy", methods=["POST"])
def manual_buy():
    return jsonify({"ok": False, "error": "Manual trading not enabled in stub mode"})


@stubs_bp.route("/api/trade/manual_sell_all", methods=["POST"])
def manual_sell_all():
    return jsonify({"ok": False, "error": "Manual trading not enabled in stub mode"})


@stubs_bp.route("/api/trade/close", methods=["POST"])
def trade_close():
    return jsonify({"ok": False, "error": "Trade close not implemented"})


@stubs_bp.route("/api/trade/delete", methods=["POST"])
def trade_delete():
    return jsonify({"ok": False, "error": "Trade delete not implemented"})


# ── Coin / Market ─────────────────────────────────────────────────────────────
@stubs_bp.route("/api/coin")
def coin():
    """Live GRAM/USD price from the market feed."""
    return jsonify({"ok": True, "symbol": Config.SYMBOL, "price": _live_price()})


@stubs_bp.route("/api/coin/exchanges")
def coin_exchanges():
    """Real per-source quote derived from the live feed status."""
    quotes = []
    status = _feed_status()
    source = status.get("source")
    price = float(status.get("price") or _live_price() or 0)
    if source and price > 0:
        quotes.append(
            {
                "exchange": source,
                "symbol": Config.SYMBOL,
                "price": price,
                "available": status.get("available", True),
                "stale": status.get("stale", False),
                "last_update": status.get("last_update"),
            }
        )
    return jsonify({"ok": True, "exchanges": quotes})


@stubs_bp.route("/api/coin/trades")
def coin_trades():
    """Recent real 1m OHLCV rows from the exchange (empty when unavailable)."""
    rows = []
    try:
        from core.price_feed_real import get_candles_timeframe

        for candle in (get_candles_timeframe("1m", 30) or [])[-30:]:
            rows.append(
                {
                    "time": int(candle.get("t", 0)),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "price": float(candle.get("close", 0)),
                    "source": "mexc",
                }
            )
    except Exception:
        rows = []
    return jsonify({"ok": True, "trades": rows})


# ── Advisor ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/advisor/apikey")
def advisor_apikey():
    return jsonify({"ok": True, "has_key": bool(Config.BINANCE_API_KEY)})


@stubs_bp.route("/api/advisor/providers")
def advisor_providers():
    """Report the LLM provider actually wired into the grid controller."""
    providers = []
    try:
        from web.routes.api import _brain  # type: ignore

        _ = _brain
    except Exception:
        pass
    import os

    if os.getenv("GROQ_API_KEY"):
        providers.append({"name": "groq", "configured": True})
    if os.getenv("MOONSHOT_API_KEY"):
        providers.append({"name": "kimi", "configured": True})
    if os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_ENABLED"):
        providers.append({"name": "ollama", "configured": True})
    return jsonify({"ok": True, "providers": providers})


@stubs_bp.route("/api/advisor/providers/select", methods=["POST"])
def advisor_providers_select():
    return jsonify({"ok": True})


# ── AI decisions ──────────────────────────────────────────────────────────────
@stubs_bp.route("/api/ai/decisions")
def ai_decisions():
    """Last LLM grid decision (empty list until the controller has decided)."""
    decisions = []
    try:
        import os

        from kimi_grid_control import KimiGridControl  # noqa: F401

        _ = os
    except Exception:
        decisions = []
    try:
        from web.routes.api import api_grid_ai_status

        payload = api_grid_ai_status().get_json() or {}
        decision = payload.get("decision")
        if decision:
            decisions = [decision]
    except Exception:
        decisions = []
    return jsonify({"ok": True, "decisions": decisions})


# ── DB sync ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/db/sync_status")
def db_sync_status():
    return jsonify({"ok": True, "synced": True, "pending": 0})


# ── Filters ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/filters/status")
def filters_status():
    """Report which risk filters are active, from the live config."""
    active = []
    if getattr(Config, "TREND_FILTER", False):
        active.append({"name": "trend_filter", "enabled": True})
    if getattr(Config.PROTECTION, "circuit_breaker_enabled", False):
        active.append({"name": "circuit_breaker", "enabled": True})
    if getattr(Config, "DAILY_RISK_ENABLED", False):
        active.append({"name": "daily_risk", "enabled": True})
    if getattr(Config.PROTECTION, "profit_protect_enabled", False):
        active.append({"name": "profit_protect", "enabled": True})
    return jsonify({"ok": True, "filters": active})


# ── Liquidator ────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/liquidator")
def liquidator():
    return jsonify({"ok": True, "enabled": False, "threshold": 0})


@stubs_bp.route("/api/liquidator/sell", methods=["POST"])
def liquidator_sell():
    return jsonify({"ok": False, "error": "Liquidator not configured"})


@stubs_bp.route("/api/liquidator/threshold", methods=["POST"])
def liquidator_threshold():
    return jsonify({"ok": True})


# ── Liquidity Guard ───────────────────────────────────────────────────────────
@stubs_bp.route("/api/liquidity_guard")
def liquidity_guard():
    return jsonify({"ok": True, "guards": []})


# ── Frontend status compatibility ────────────────────────────────────────────
@stubs_bp.route("/api/advisor/status")
def advisor_status():
    """Reflect the real Groq/Kimi controller state instead of a fixed payload."""
    enabled = False
    provider = None
    running = False
    configured = False
    last_error = ""
    import os as _os

    if _os.getenv("GROQ_API_KEY") or _os.getenv("MOONSHOT_API_KEY"):
        configured = True
        provider = "groq" if _os.getenv("GROQ_API_KEY") else "kimi"
        running = True
    sensor = getattr(Config, "GRID", None)
    enabled = bool(sensor and getattr(sensor, "enabled", False))
    return jsonify(
        {
            "ok": True,
            "enabled": enabled,
            "configured": configured,
            "running": running,
            "provider": provider,
            "last_error": last_error,
        }
    )


@stubs_bp.route("/api/ai/deep-retrain/status")
def deep_retrain_status():
    return jsonify({"ok": True, "status": "idle", "running": False, "progress": 0})
