"""Security tests — HMAC, circuit breaker, input validation."""

import pytest
from unittest.mock import patch

from ai.engine import AIEngine, _sign_data, _verify_data
from circuit_breaker import CircuitBreaker, CircuitBreakerOpen, State
from validators import SettingsUpdate, LoginRequest, WithdrawRequest


class TestHMAC:
    def test_sign_verify_roundtrip(self):
        with patch("core.config.Config.SECRET_KEY", "test-secret-key-32bytes-long!!"):
            data = b"test payload"
            signed = _sign_data(data)
            assert signed != data
            assert _verify_data(signed) == data

    def test_tamper_detected(self):
        with patch("core.config.Config.SECRET_KEY", "test-secret-key-32bytes-long!!"):
            data = b"test payload"
            signed = _sign_data(data)
            tampered = signed[:10] + b"X" + signed[11:]
            with pytest.raises(ValueError, match="tampering"):
                _verify_data(tampered)

    def test_missing_secret_key_raises(self):
        with patch("core.config.Config.SECRET_KEY", ""):
            with pytest.raises(RuntimeError):
                _sign_data(b"data")


class TestCircuitBreaker:
    def test_closed_allows_calls(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.state == State.CLOSED

    def test_opens_after_failures(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.call(lambda: 42)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == State.OPEN
        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: 42)

    def test_decorator(self):
        cb = CircuitBreaker("decorator", failure_threshold=1)

        @cb
        def flaky():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            flaky()
        with pytest.raises(CircuitBreakerOpen):
            flaky()


class TestValidators:
    def test_settings_update_valid(self):
        s = SettingsUpdate(trade_amount=10.0, step_pct=3.5)
        assert s.trade_amount == 10.0

    def test_settings_update_invalid_negative(self):
        with pytest.raises(ValueError):
            SettingsUpdate(trade_amount=-5.0)

    def test_login_request(self):
        l = LoginRequest(username="admin", password="secret")
        assert l.username == "admin"

    def test_withdraw_request(self):
        w = WithdrawRequest(amount=1.5, address="EQ...")
        assert w.amount == 1.5

    def test_withdraw_zero_amount_rejected(self):
        with pytest.raises(ValueError):
            WithdrawRequest(amount=0, address="EQ...")
