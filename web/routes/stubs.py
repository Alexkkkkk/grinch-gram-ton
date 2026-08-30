#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════════
# Stub routes — return empty/default data for frontend compatibility.
# These endpoints are called by the SPA dashboard but not yet implemented
# in the trading backend. They prevent 404 errors in browser console.
# ═══════════════════════════════════════════════════════════════════════════════

from flask import Blueprint, jsonify

from core.config import Config

stubs_bp = Blueprint("stubs", __name__)


# ── Trading control ───────────────────────────────────────────────────────────
@stubs_bp.route("/api/start", methods=["POST"])
def start_bot():
    return jsonify({"ok": True, "message": "Bot start requested", "mode": Config.TRADE_MODE})


@stubs_bp.route("/api/stop", methods=["POST"])
def stop_bot():
    return jsonify({"ok": True, "message": "Bot stop requested"})


# ── TON info ──────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/ton")
def ton_info():
    return jsonify({"ok": True, "wallet": Config.TON_WALLET, "network": "mainnet"})


@stubs_bp.route("/api/ton/price")
def ton_price():
    try:
        price = getattr(Config, "TON", {}).get("price_usd", 0) if hasattr(Config, "TON") else 0
    except Exception:
        price = 0
    return jsonify({"ok": True, "price_usd": price, "price_ton": 1.0})


@stubs_bp.route("/api/ton/refresh", methods=["POST"])
def ton_refresh():
    return jsonify({"ok": True, "message": "Price refresh requested"})


# ── Wallets ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/wallets")
def wallets():
    return jsonify({"ok": True, "wallets": [{"address": Config.TON_WALLET, "type": "ton", "balance": 0}]})


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
    try:
        price = getattr(Config, "TON", {}).get("price_usd", 0) if hasattr(Config, "TON") else 0
    except Exception:
        price = 0
    return jsonify({"ok": True, "symbol": Config.SYMBOL, "price": price})


@stubs_bp.route("/api/coin/exchanges")
def coin_exchanges():
    return jsonify({"ok": True, "exchanges": []})


@stubs_bp.route("/api/coin/trades")
def coin_trades():
    return jsonify({"ok": True, "trades": []})


# ── Advisor ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/advisor/apikey")
def advisor_apikey():
    return jsonify({"ok": True, "has_key": bool(Config.BINANCE_API_KEY)})


@stubs_bp.route("/api/advisor/providers")
def advisor_providers():
    return jsonify({"ok": True, "providers": []})


@stubs_bp.route("/api/advisor/providers/select", methods=["POST"])
def advisor_providers_select():
    return jsonify({"ok": True})


# ── AI decisions ──────────────────────────────────────────────────────────────
@stubs_bp.route("/api/ai/decisions")
def ai_decisions():
    return jsonify({"ok": True, "decisions": []})


# ── DB sync ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/db/sync_status")
def db_sync_status():
    return jsonify({"ok": True, "synced": True, "pending": 0})


# ── Filters ───────────────────────────────────────────────────────────────────
@stubs_bp.route("/api/filters/status")
def filters_status():
    return jsonify({"ok": True, "filters": []})


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
    return jsonify(
        {
            "ok": True,
            "enabled": False,
            "configured": False,
            "running": False,
            "provider": None,
        }
    )


@stubs_bp.route("/api/ai/deep-retrain/status")
def deep_retrain_status():
    return jsonify({"ok": True, "status": "idle", "running": False, "progress": 0})


@stubs_bp.route("/api/grid/ai/status")
def grid_ai_status():
    return jsonify(
        {
            "ok": True,
            "enabled": True,
            "signal": "HOLD",
            "confidence": 0.0,
            "trap_detected": False,
            "pause_buying": False,
        }
    )
