"""Regression tests for manual startup and optional operational tooling."""

from pathlib import Path


def test_manual_start_uses_real_entrypoint():
    run_script = (Path(__file__).parents[1] / "run.sh").read_text()
    assert "main:app" in run_script
    assert "\npython3 app.py" not in run_script


def test_optional_modules_import():
    from autonomy.auto_updater import AutoUpdater
    from autonomy.performance_monitor import PerformanceMonitor
    from web.middleware import ErrorHandlerMiddleware, TimingMiddleware

    assert AutoUpdater
    assert PerformanceMonitor
    assert ErrorHandlerMiddleware
    assert TimingMiddleware


def test_auto_updater_interval_is_positive():
    from autonomy.auto_updater import AutoUpdater

    assert AutoUpdater(check_interval_hours=0).check_interval_hours > 0
