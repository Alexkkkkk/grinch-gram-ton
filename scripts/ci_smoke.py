"""CI smoke test — verifies all imports and basic functionality."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_core():
    from core.base_components import GridLevel, NpEncoder
    from core.config import Config

    assert Config.SYMBOL
    assert Config.GRID.symbol
    assert Config.GRID.step_pct == 3.5
    assert Config.FEES.round_trip > 0
    gl = GridLevel(1.0, "buy", 100)
    assert gl.price == 1.0
    import numpy as np

    assert NpEncoder().default(np.int64(5)) == 5
    print("  core/ OK")


def test_compat():
    from ai import QuantumEngine
    from core.config import Config

    assert Config.SYMBOL
    assert QuantumEngine is not None
    print("  compat/ OK")


def test_ai():
    from ai import QuantumEngine

    assert QuantumEngine.__name__ == "AIEngine"
    print("  ai/ OK (lazy)")


def test_trading():
    from trading.position_manager import PositionManager

    pm = PositionManager()
    assert pm.get_open_positions() == []
    print("  trading/ OK")


def test_db():
    from db.repositories import TradeRepository

    assert TradeRepository is not None
    print("  db/ OK")


def test_web():
    from web.app import create_app

    app = create_app()
    assert app is not None
    with app.test_client() as client:
        rv = client.get("/api/health")
        assert rv.status_code == 200
        assert rv.get_json()["status"] == "healthy"
    print("  web/ OK")


def test_config_methods():
    from core.config import Config

    gross = Config.required_gross_pct(100)
    assert gross > 0
    print("  config methods OK")


if __name__ == "__main__":
    print("Running CI smoke tests...")
    test_core()
    test_compat()
    test_ai()
    test_trading()
    test_db()
    test_web()
    test_config_methods()
    print("\nCI SMOKE PASSED")
