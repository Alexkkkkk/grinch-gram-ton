"""Kimi-powered control layer for the AI Grid.

Kimi may recommend a grid action and sizing, but it never receives wallet
credentials and never has a tool that can place an order. GridTrader remains
the only component allowed to call the exchange client.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger("kimi_grid_control")

_ALLOWED_ACTIONS = {"WAIT", "BUILD", "START", "PAUSE_BUY", "STOP"}
_ALLOWED_SIGNALS = {"BUY", "SELL", "HOLD"}


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class KimiGridControl:
    """Rate-limited, fail-closed Kimi recommender for grid control."""

    def __init__(self):
        self.api_key = os.getenv("MOONSHOT_API_KEY", "").strip()
        self.enabled = bool(self.api_key) and _bool_env("KIMI_CONTROL_ENABLED", True)
        self.required_for_auto_grid = _bool_env("KIMI_REQUIRE_FOR_AUTO_GRID", True)
        self.model = os.getenv("KIMI_MODEL", "kimi-k2.6").strip() or "kimi-k2.6"
        self.base_url = (
            os.getenv("KIMI_API_BASE", "https://api.moonshot.ai/v1").strip()
            or "https://api.moonshot.ai/v1"
        )
        self.min_confidence = max(
            0.0, min(100.0, _float_env("KIMI_MIN_CONFIDENCE", 60.0))
        )
        self.interval_sec = max(15.0, _float_env("KIMI_CALL_INTERVAL_SEC", 60.0))
        self.timeout_sec = max(3.0, _float_env("KIMI_TIMEOUT_SEC", 12.0))
        self.max_total_levels = max(2, int(_float_env("KIMI_MAX_TOTAL_LEVELS", 40)))
        self._client = None
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._last_decision: Optional[Dict[str, Any]] = None
        self._last_error = ""

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_sec,
                max_retries=0,
            )
        return self._client

    @staticmethod
    def _parse_content(content: Any) -> Dict[str, Any]:
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        text = str(content or "").strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Kimi response is not an object")
        return parsed

    def _validate(
        self,
        raw: Dict[str, Any],
        fallback_step: float,
        defaults: Dict[str, Any],
        wallet: Dict[str, Any],
    ) -> Dict[str, Any]:
        action = str(raw.get("action", "WAIT")).upper().strip()
        signal = str(raw.get("signal", "HOLD")).upper().strip()
        if action not in _ALLOWED_ACTIONS:
            action = "WAIT"
        if signal not in _ALLOWED_SIGNALS:
            signal = "HOLD"
        try:
            confidence = max(0.0, min(100.0, float(raw.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            step = float(raw.get("step_pct", fallback_step))
        except (TypeError, ValueError):
            step = fallback_step
        min_step = max(0.1, _float_env("GRID_MIN_STEP_PCT", 0.9))
        max_step = max(min_step, _float_env("GRID_MAX_STEP_PCT", 8.0))
        step = max(min_step, min(max_step, step))

        def int_value(name: str, fallback: int) -> int:
            try:
                return int(float(raw.get(name, fallback)))
            except (TypeError, ValueError):
                return fallback

        configured_sell = max(1, int(_float_env("GRID_SELL_LEVELS", defaults["sell_levels"])))
        configured_buy = max(0, int(_float_env("GRID_BUY_LEVELS", defaults["buy_levels"])))
        sell_levels = max(
            1,
            min(
                self.max_total_levels - 1,
                configured_sell,
                int_value("sell_levels", configured_sell),
            ),
        )
        buy_levels = max(
            0,
            min(
                self.max_total_levels - sell_levels,
                configured_buy,
                int_value("buy_levels", configured_buy),
            ),
        )
        investment = raw.get("investment_ton", defaults.get("investment_ton"))
        if investment is not None:
            try:
                investment = max(0.0, float(investment))
                available_ton = wallet.get("ton")
                if available_ton is not None:
                    investment = min(investment, max(0.0, float(available_ton)))
                investment = round(investment, 6)
            except (TypeError, ValueError):
                investment = defaults.get("investment_ton")
        reason = str(raw.get("reason", "")).strip().replace("\n", " ")[:240]
        return {
            "signal": signal,
            "confidence": round(confidence, 1),
            "action": action,
            "step_pct": round(step, 2),
            "investment_ton": investment,
            "sell_levels": sell_levels,
            "buy_levels": buy_levels,
            "reason": reason,
            "model": self.model,
            "updated_at": time.time(),
        }

    def decide(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Ask Kimi for a recommendation when the rate limit permits."""
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            if now - self._last_request_at < self.interval_sec:
                return self._last_decision
            self._last_request_at = now

        local = market.get("local", {})
        defaults = market.get("defaults", {})
        wallet = market.get("wallet", {})
        fallback_step = float(local.get("optimal_step", _float_env("GRID_STEP_PCT", 0.9)) or _float_env("GRID_STEP_PCT", 0.9))
        system = (
            "You are the risk-aware controller for a spot cryptocurrency grid. "
            "You are advisory only: never invent balances, never place orders, "
            "and never recommend leverage or shorting. Use the wallet balances "
            "and limits supplied by the user context. Return JSON only with "
            "exactly these keys: signal (BUY, SELL, HOLD), confidence (0-100), "
            "action (WAIT, BUILD, START, PAUSE_BUY, STOP), step_pct (the configured grid range), "
            "investment_ton (non-negative), sell_levels (1-39), buy_levels (0-39), "
            "reason (short string). The sum of levels must not exceed the supplied "
            "limit. Never set investment_ton above available TON. STOP is reserved "
            "for clear danger; PAUSE_BUY stops new buys but allows existing sells."
        )
        user = json.dumps(market, ensure_ascii=False, separators=(",", ":"))
        try:
            response = self._get_client().chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            decision = self._validate(
                content and self._parse_content(content),
                fallback_step,
                defaults,
                wallet,
            )
        except Exception as exc:
            raw_error = str(exc).lower()
            if "insufficient balance" in raw_error or "insufficient funds" in raw_error:
                safe_error = "account balance is insufficient"
            elif (
                "401" in raw_error
                or "403" in raw_error
                or "authentication" in raw_error
            ):
                safe_error = "authentication or permission error"
            elif "429" in raw_error or "rate limit" in raw_error:
                safe_error = "rate limit reached"
            else:
                safe_error = "request failed"
            self._last_error = f"{type(exc).__name__}: {safe_error}"
            log.warning("[Kimi] recommendation unavailable: %s", self._last_error)
            return self._last_decision

        with self._lock:
            self._last_decision = decision
            self._last_error = ""
        log.info(
            "[Kimi] decision=%s signal=%s confidence=%.1f step=%.2f investment=%s levels=%s/%s",
            decision["action"],
            decision["signal"],
            decision["confidence"],
            decision["step_pct"],
            decision["investment_ton"],
            decision["sell_levels"],
            decision["buy_levels"],
        )
        return decision

    def status(self) -> Dict[str, Any]:
        with self._lock:
            decision = dict(self._last_decision) if self._last_decision else None
            return {
                "enabled": self.enabled,
                "required_for_auto_grid": self.required_for_auto_grid,
                "ready": decision is not None,
                "model": self.model,
                "last_error": self._last_error,
                "decision": decision,
            }
