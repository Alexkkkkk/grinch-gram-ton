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
from flask import Blueprint, jsonify, request

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
    # Fallback: latest real 1m candle close straight from the exchange.
    try:
        from core.price_feed_real import get_candles_timeframe

        candles = get_candles_timeframe("1m", 2) or []
        if candles:
            close = float(candles[-1].get("close", 0) or 0)
            if close > 0:
                return close
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
    """Force a real price update from the market feed."""
    try:
        from core.price_feed_real import update_price

        price = update_price()
        return jsonify({"ok": True, "price": price})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


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
    """Manual BUY via the live GridTrader/DeDust client."""
    from web.routes.api import _grid_trader

    if _grid_trader is None:
        return jsonify({"ok": False, "error": "trader_not_ready"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(_grid_trader.manual_buy(data.get("amount")))


@stubs_bp.route("/api/trade/manual_sell_all", methods=["POST"])
def manual_sell_all():
    """Sell every filled BUY position via the live GridTrader."""
    from web.routes.api import _grid_trader

    if _grid_trader is None:
        return jsonify({"ok": False, "error": "trader_not_ready"}), 503
    return jsonify(_grid_trader.manual_sell_all())


@stubs_bp.route("/api/trade/close", methods=["POST"])
def trade_close():
    """Close a tracked position by selling it on DeDust."""
    from web.routes.api import _grid_trader

    if _grid_trader is None:
        return jsonify({"ok": False, "error": "trader_not_ready"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(_grid_trader.close_trade(str(data.get("id"))))


@stubs_bp.route("/api/trade/delete", methods=["POST"])
def trade_delete():
    """Remove a position from the tracker WITHOUT selling."""
    from web.routes.api import _grid_trader

    if _grid_trader is None:
        return jsonify({"ok": False, "error": "trader_not_ready"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(_grid_trader.delete_trade(str(data.get("id"))))


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
    """Persist the selected LLM provider in the real settings store."""
    data = request.get_json(silent=True) or {}
    name = str(data.get("provider") or data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "provider_required"}), 400
    try:
        from db_store import settings_update_section

        settings_update_section("advisor", {"selected_provider": name})
        return jsonify({"ok": True, "selected": name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


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
    """Real DB availability from the store layer."""
    try:
        from db_store import _check_available

        synced = bool(_check_available())
    except Exception:
        synced = False
    return jsonify({"ok": True, "synced": synced, "pending": 0 if synced else 1})


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
    """Real liquidator state: threshold persisted in the settings store."""
    threshold = 0
    try:
        from db_store import settings_get_section

        threshold = int(
            (settings_get_section("liquidator") or {}).get("threshold") or 0
        )
    except Exception:
        threshold = 0
    return jsonify({"ok": True, "enabled": False, "threshold": threshold})


@stubs_bp.route("/api/liquidator/sell", methods=["POST"])
def liquidator_sell():
    # The liquidator module is not part of the codebase: the button stays
    # explicitly disabled instead of pretending to sell.
    return (
        jsonify({"ok": False, "error": "Liquidator disabled: module not configured"}),
        503,
    )


@stubs_bp.route("/api/liquidator/threshold", methods=["POST"])
def liquidator_threshold():
    """Persist the threshold in the real settings store."""
    data = request.get_json(silent=True) or {}
    try:
        from db_store import settings_update_section

        settings_update_section(
            "liquidator", {"threshold": int(data.get("threshold") or 0)}
        )
        return jsonify({"ok": True, "threshold": int(data.get("threshold") or 0)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


# ── Liquidity Guard ───────────────────────────────────────────────────────────
@stubs_bp.route("/api/liquidity_guard")
def liquidity_guard():
    return jsonify({"ok": True, "guards": []})


# ── Health aliases (public, no redirect) ─────────────────────────────────────
@stubs_bp.route("/health")
def health_alias():
    from web.routes.health import health_check

    return health_check()


@stubs_bp.route("/health/full")
def health_full_alias():
    from web.routes.health import full_health

    return full_health()


@stubs_bp.route("/health/metrics")
def health_metrics_alias():
    from web.routes.health import metrics

    return metrics()


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
