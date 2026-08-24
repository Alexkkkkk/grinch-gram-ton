"""Dashboard blueprint — HTML views."""

from flask import Blueprint, render_template, jsonify

from core.config import Config

dash_bp = Blueprint("dash", __name__)


@dash_bp.route("/")
def index():
    return render_template("grid_dashboard.html")


@dash_bp.route("/dashboard")
def dashboard():
    return render_template("grid_dashboard.html")


@dash_bp.route("/api/dashboard/data")
def dashboard_data():
    """JSON data for SPA dashboard."""
    return jsonify(
        {
            "symbol": Config.SYMBOL,
            "price": Config.GRID.symbol,
            "grid": {
                "enabled": Config.GRID.enabled,
                "step_pct": Config.GRID.step_pct,
                "levels": Config.GRID.count,
            },
            "fees": {
                "pct": Config.FEES.pct,
                "round_trip": Config.FEES.round_trip,
            },
        }
    )
