"""Groq-powered control layer for the AI Grid.

Kimi may recommend a grid action and sizing, but it never receives wallet
credentials and never has a tool that can place an order. GridTrader remains
the only component allowed to call the exchange client.
"""

import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger("kimi_grid_control")

_ALLOWED_ACTIONS = {"WAIT", "BUILD", "START", "REBUILD", "PAUSE_BUY", "STOP"}
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
    """Rate-limited, fail-closed AI recommender for grid control.

    The historical class name is kept for compatibility with the rest of the
    application. Groq is preferred when GROQ_API_KEY is configured; Moonshot
    remains a backwards-compatible fallback. The model manages grid
    parameters, but never receives credentials or a tool that can place orders.
    """

    def __init__(self):
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        kimi_key = os.getenv("MOONSHOT_API_KEY", "").strip()
        ollama_url = os.getenv("OLLAMA_BASE_URL", "").strip()
        llamafile_url = os.getenv("LLAMAFILE_BASE_URL", "").strip()
        if groq_key:
            self.provider = "groq"
        elif kimi_key:
            self.provider = "kimi"
        elif llamafile_url:
            self.provider = "llamafile"
        elif ollama_url or _bool_env("OLLAMA_ENABLED", False):
            self.provider = "ollama"
        else:
            self.provider = "none"
        # URL из *_BASE_URL имеет приоритет; иначе берём prefix-based env или дефолт.
        self.base_url = (llamafile_url or ollama_url or "").rstrip("/")
        if (
            not self.base_url
            and self.provider == "ollama"
            and _bool_env("OLLAMA_ENABLED", False)
        ):
            self.base_url = "http://127.0.0.1:11434/v1"
        prefix = self.provider.upper() if self.provider != "none" else "GROQ"
        # Local providers (Ollama/llamafile) don't need a real key, but the
        # OpenAI client requires a non-empty one.
        self.api_key = groq_key or kimi_key or "local-not-needed"
        self.enabled = (
            bool(groq_key or kimi_key) or self.provider in ("ollama", "llamafile")
        ) and _bool_env(f"{prefix}_CONTROL_ENABLED", True)
        self.required_for_auto_grid = _bool_env(f"{prefix}_REQUIRE_FOR_AUTO_GRID", True)
        _model_defaults = {
            "groq": "qwen/qwen3.8-27b",
            "kimi": "kimi-k2.6",
            "ollama": "llama3.1:8b",
            "llamafile": "llamafile",
        }
        self.model = (
            os.getenv(f"{prefix}_MODEL", "")
            or _model_defaults.get(self.provider, "kimi-k2.6")
        ).strip()
        _base_defaults = {
            "groq": "https://api.groq.com/openai/v1",
            "kimi": "https://api.moonshot.ai/v1",
            "ollama": "http://127.0.0.1:11434/v1",
            "llamafile": "http://127.0.0.1:8080/v1",
        }
        if not self.base_url:
            self.base_url = os.getenv(
                f"{prefix}_API_BASE", ""
            ).strip() or _base_defaults.get(self.provider, "https://api.moonshot.ai/v1")
        self.min_confidence = max(
            0.0, min(100.0, _float_env(f"{prefix}_MIN_CONFIDENCE", 60.0))
        )
        self.interval_sec = max(15.0, _float_env(f"{prefix}_CALL_INTERVAL_SEC", 60.0))
        self.timeout_sec = max(3.0, _float_env(f"{prefix}_TIMEOUT_SEC", 12.0))
        self.max_total_levels = max(
            2, int(_float_env(f"{prefix}_MAX_TOTAL_LEVELS", 40))
        )
        self._client = None
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._last_decision: Optional[Dict[str, Any]] = None
        self._last_error = ""
        # Rate-limit backoff (429): skip calls until this monotonic deadline.
        self._rl_backoff_until = 0.0
        # Cached verdict for response_format support: None = unknown,
        # True = accepted, False = rejected (do not send it again).
        self._response_format_ok: Optional[bool] = None
        # Client-side TPM throttle. Live limits of this key were confirmed
        # from x-ratelimit-* headers (TPM = 8000 tokens/min, free tier), so
        # the client keeps its own accounting just below the hard cap.
        # Events: (monotonic_ts, tokens) within the trailing 60s window.
        self._tpm_events: list = []
        self._tpm_budget = max(0.0, _float_env(f"{prefix}_TPM_BUDGET", 7500.0))
        self._rl_attempts = 0

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
    def _estimate_tokens(*texts: str) -> int:
        """Rough request size in tokens (~4 chars per token for JSON)."""
        return max(1, sum(len(t or "") for t in texts) // 4)

    def _tpm_reserve(self, estimated: int) -> bool:
        """True when the request fits into the client-side TPM budget.

        The estimate is accounted immediately; _tpm_account() replaces it
        with the real usage total once the response arrives.
        """
        if self._tpm_budget <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            self._tpm_events = [
                (ts, tk) for ts, tk in self._tpm_events if now - ts < 60.0
            ]
            if sum(tk for _, tk in self._tpm_events) + estimated > self._tpm_budget:
                return False
            self._tpm_events.append((now, estimated))
            return True

    def _tpm_account(self, estimated: int, actual: int) -> None:
        """Replace the pre-call estimate with the real usage total.

        actual == 0 means the request failed and consumed nothing: the
        estimate is simply released.
        """
        with self._lock:
            now = time.monotonic()
            self._tpm_events = [
                (ts, tk) for ts, tk in self._tpm_events if now - ts < 60.0
            ]
            try:
                idx = next(
                    i for i, (_, tk) in enumerate(self._tpm_events) if tk == estimated
                )
                self._tpm_events.pop(idx)
            except StopIteration:
                pass
            if actual > 0:
                self._tpm_events.append((now, max(1, int(actual))))

    @staticmethod
    def _parse_duration(text: str) -> float:
        """Parse Groq reset strings like '2m52.8s', '547ms', '1h0m0s' to seconds."""
        total = 0.0
        for value, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", text or ""):
            amount = float(value)
            if unit == "ms":
                total += amount / 1000.0
            elif unit == "s":
                total += amount
            elif unit == "m":
                total += amount * 60.0
            elif unit == "h":
                total += amount * 3600.0
        if total == 0.0 and text and text.strip().replace(".", "", 1).isdigit():
            total = float(text.strip())
        return total

    def _learn_rate_limit(self, exc: Exception):
        """Read retry-after / x-ratelimit-* headers from a 429 response.

        Returns (pause_seconds, bucket, remedy): which limit died (RPM/TPM/TPD)
        decides the pause length and the right long-term fix.
        """
        headers = {}
        response = getattr(exc, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None) or {}

        def hget(name):
            try:
                value = headers.get(name)
            except AttributeError:
                value = None
            return value.strip() if isinstance(value, str) else ""

        retry_after = self._parse_duration(hget("retry-after"))
        reset_tokens = self._parse_duration(hget("x-ratelimit-reset-tokens"))
        reset_requests = self._parse_duration(hget("x-ratelimit-reset-requests"))
        remaining_tokens = hget("x-ratelimit-remaining-tokens")
        remaining_requests = hget("x-ratelimit-remaining-requests")
        log.info(
            "[%s-RL] 429 headers: retry-after=%s reset-tokens=%s "
            "reset-requests=%s remaining-tokens=%s remaining-requests=%s",
            self.provider.upper(),
            hget("retry-after") or "-",
            hget("x-ratelimit-reset-tokens") or "-",
            hget("x-ratelimit-reset-requests") or "-",
            remaining_tokens or "-",
            remaining_requests or "-",
        )
        low = str(exc).lower()
        default_pause = max(
            15.0,
            _float_env(f"{self.provider.upper()}_RATE_LIMIT_BACKOFF_SEC", 1800.0),
        )
        if "per day" in low or "tpd" in low:
            pause = retry_after or max(reset_tokens, reset_requests) or 21600.0
            bucket = "TPD (daily token quota)"
            remedy = "switch model or wait for the daily reset"
        elif (
            "rpm" in low
            or (not reset_tokens and reset_requests > 0)
            or (remaining_requests == "0" and not remaining_tokens)
        ):
            # Retry only when the server allows it AND the RPM bucket refilled,
            # otherwise the very next request 429s again.
            pause = max(retry_after, reset_requests) or 60.0
            bucket = "RPM (requests per minute)"
            remedy = "calls will queue up automatically"
        else:
            # Same rule for TPM: wait past retry-after AND the token reset,
            # since an early retry would burn nothing but fail anyway.
            pause = max(retry_after, reset_tokens) or default_pause
            bucket = "TPM (tokens per minute)"
            remedy = "shrink the prompt or cap max_completion_tokens"
        return min(max(pause, 15.0), 86400.0), bucket, remedy

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
            raise ValueError("AI response is not an object")
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
        ai_manages_grid = self.provider in (
            "groq",
            "ollama",
            "llamafile",
        ) and _bool_env(
            f"{self.provider.upper()}_MANAGES_GRID",
            _bool_env("GROQ_MANAGES_GRID", True),
        )
        if not ai_manages_grid and not _bool_env("GRID_ADAPTIVE_STEP", False):
            step = _float_env("GRID_STEP_PCT", min_step)
        else:
            step = max(min_step, min(max_step, step))

        def int_value(name: str, fallback: int) -> int:
            try:
                return int(float(raw.get(name, fallback)))
            except (TypeError, ValueError):
                return fallback

        configured_sell = max(
            1, int(_float_env("GRID_SELL_LEVELS", defaults["sell_levels"]))
        )
        configured_buy = max(
            0, int(_float_env("GRID_BUY_LEVELS", defaults["buy_levels"]))
        )
        sell_levels = max(
            1,
            min(self.max_total_levels - 1, int_value("sell_levels", configured_sell)),
        )
        buy_levels = max(
            0,
            min(
                self.max_total_levels - sell_levels,
                int_value("buy_levels", configured_buy),
            ),
        )
        investment = raw.get("investment_ton", defaults.get("investment_ton"))
        available_ton = wallet.get("ton")
        gas_reserve = max(0.0, _float_env("GAS_RESERVE_TON", 0.3))
        if investment is not None:
            try:
                investment = max(0.0, float(investment))
                if available_ton is not None:
                    # The model may plan only with capital that remains after
                    # the wallet's untouchable network-fee reserve.
                    investment = min(
                        investment,
                        max(0.0, float(available_ton) - gas_reserve),
                    )
                investment = round(investment, 6)
            except (TypeError, ValueError):
                investment = defaults.get("investment_ton")
        sell_as_ton = _bool_env("GRID_SELL_AS_TON", False)
        funded_levels = sell_levels if sell_as_ton else buy_levels
        ton_per_step = raw.get("ton_per_step")
        try:
            ton_per_step = (
                max(0.0, float(ton_per_step)) if ton_per_step is not None else None
            )
        except (TypeError, ValueError):
            ton_per_step = None
        if ton_per_step is None and investment is not None and funded_levels > 0:
            ton_per_step = max(0.0, float(investment) / funded_levels)
        if ton_per_step is not None and available_ton is not None and funded_levels > 0:
            ton_per_step = min(
                ton_per_step,
                max(0.0, float(available_ton) - gas_reserve) / funded_levels,
            )
            ton_per_step = round(ton_per_step, 6)

        reason = str(raw.get("reason", "")).strip().replace("\n", " ")[:240]
        return {
            "signal": signal,
            "confidence": round(confidence, 1),
            "action": action,
            "step_pct": round(step, 2),
            "investment_ton": investment,
            "ton_per_step": ton_per_step,
            "sell_levels": sell_levels,
            "buy_levels": buy_levels,
            "reason": reason,
            "model": self.model,
            "updated_at": time.time(),
        }

    def decide(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Ask Groq/Kimi for a recommendation when the rate limit permits."""
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            if now - self._last_request_at < self.interval_sec:
                return self._last_decision
            if now < self._rl_backoff_until:
                # Rate-limit backoff active: do not probe the API, reuse the
                # last known decision until the reset window passes.
                return self._last_decision
            self._last_request_at = now

        local = market.get("local", {})
        defaults = market.get("defaults", {})
        wallet = market.get("wallet", {})
        fallback_step = float(
            local.get("optimal_step", _float_env("GRID_STEP_PCT", 0.9))
            or _float_env("GRID_STEP_PCT", 0.9)
        )
        system = (
            "You are the risk-aware controller for a spot cryptocurrency grid. "
            "You manage grid parameters only; never invent balances, never place orders, "
            "and never recommend leverage or shorting. Use the wallet balances "
            "and limits supplied by the user context. Treat gas_reserve_ton as untouchable. "
            "Subtract fee_pct, slippage_pct, and estimated gas costs before sizing a grid; "
            "never spend the gas reserve. Use REBUILD when the active grid "
            "should be adapted to current market conditions or wallet balances; "
            "otherwise use WAIT. When the step, per-level amount, or level counts "
            "should change, use REBUILD so the controller applies the new grid. "
            "Return JSON only with exactly these keys: signal (BUY, SELL, HOLD), "
            "confidence (0-100), action (WAIT, BUILD, START, REBUILD, PAUSE_BUY, STOP), "
            "step_pct (the grid price step in percent), investment_ton (total TON budget), "
            "ton_per_step (TON amount for each funded level), sell_levels (1-39), "
            "buy_levels (0-39), reason (short string). The sum of levels must not exceed "
            "the supplied limit. The controller will cap ton_per_step and investment_ton "
            "to the wallet after the gas reserve. Never set investment_ton above available TON. STOP is reserved "
            "for clear danger; PAUSE_BUY stops new buys but allows existing sells."
        )
        user = json.dumps(market, ensure_ascii=False, separators=(",", ":"))
        # response_format json_object поддерживают Groq/Kimi; локальные
        # серверы (Ollama/llamafile) старее могут его не принимать — системный
        # промпт требует JSON-only, а _parse_content умеет снимать ```json fence.
        request_kwargs: Dict[str, Any] = {}
        if self.provider in ("groq", "kimi") and self._response_format_ok is not False:
            request_kwargs["response_format"] = {"type": "json_object"}
        # Cap completion tokens: with a small per-minute token budget
        # (free-tier Groq TPM can be as low as 8K) an uncapped completion
        # drains the whole bucket in one request.
        _max_out = _float_env(f"{self.provider.upper()}_MAX_OUTPUT_TOKENS", 0.0)
        if _max_out > 0 and self.provider in ("groq", "kimi"):
            request_kwargs["max_completion_tokens"] = int(_max_out)
        # Client-side TPM gate: skip the cycle when the request would not
        # fit into the remaining per-minute token budget.
        est_tokens = self._estimate_tokens(system, user)
        if not self._tpm_reserve(est_tokens):
            with self._lock:
                self._rl_backoff_until = max(
                    self._rl_backoff_until, time.monotonic() + 15.0
                )
            log.info(
                "[%s] client TPM budget reached (est ~%d tok in 60s window, "
                "budget %.0f) — skipping this cycle",
                self.provider.upper(),
                est_tokens,
                self._tpm_budget,
            )
            return self._last_decision
        usage_accounted = False
        try:
            try:
                response = self._get_client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    **request_kwargs,
                )
            except Exception as exc:
                # Some Groq models reject response_format={"type": "json_object"}
                # with a BadRequest/400. Cache the rejection and retry once
                # without it: the system prompt already demands JSON-only and
                # _parse_content strips ```json. Without the cache every cycle
                # burned two requests (and the retry could hit a 429).
                if (
                    "response_format" in request_kwargs
                    and self._response_format_ok is not False
                    and (
                        "badrequest" in type(exc).__name__.lower() or "400" in str(exc)
                    )
                ):
                    self._response_format_ok = False
                    request_kwargs.pop("response_format", None)
                    # The rejected request consumed no tokens: release the
                    # estimate so the retry accounts its own usage.
                    self._tpm_account(est_tokens, 0)
                    log.warning(
                        "[%s] json_object rejected (%s) — retrying without "
                        "response_format (verdict cached for future cycles)",
                        self.provider.upper(),
                        type(exc).__name__,
                    )
                    response = self._get_client().chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        **request_kwargs,
                    )
                else:
                    raise
            content = response.choices[0].message.content
            usage = getattr(response, "usage", None)
            if usage is not None:
                self._tpm_account(
                    est_tokens,
                    int(getattr(usage, "total_tokens", 0) or 0),
                )
                usage_accounted = True
            decision = self._validate(
                content and self._parse_content(content),
                fallback_step,
                defaults,
                wallet,
            )
        except Exception as exc:
            # A failed request consumed no tokens: release the estimate,
            # unless the success path already replaced it with real usage.
            if not usage_accounted:
                self._tpm_account(est_tokens, 0)
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
                # Trust the server's own headers: retry-after and the reset
                # windows say exactly which bucket (RPM/TPM/TPD) is exhausted
                # and how long to wait instead of probing every cycle.
                self._rl_attempts += 1
                _pause, _bucket, _remedy = self._learn_rate_limit(exc)
                # Respect Retry-After (lower bound) and escalate with
                # exponential backoff + jitter on repeated 429s, capped
                # so the controller never hot-loops the API.
                _base = max(
                    5.0,
                    _float_env(f"{self.provider.upper()}_RATE_BACKOFF_BASE_SEC", 60.0),
                )
                _cap = max(
                    15.0,
                    _float_env(
                        f"{self.provider.upper()}_RATE_LIMIT_BACKOFF_SEC", 1800.0
                    ),
                )
                _exp = min(
                    _base * (2 ** min(self._rl_attempts, 6))
                    + random.uniform(0.0, _base * 0.25),
                    _cap,
                )
                _pause = max(_pause, min(_exp, _cap))
                with self._lock:
                    self._rl_backoff_until = time.monotonic() + _pause
                log.warning(
                    "[%s] 429: %s exhausted — pausing AI recommendations "
                    "for %.0fs (remedy: %s)",
                    self.provider.upper(),
                    _bucket,
                    _pause,
                    _remedy,
                )
            else:
                safe_error = "request failed"
            self._last_error = f"{type(exc).__name__}: {safe_error}"
            log.warning(
                "[%s] recommendation unavailable: %s",
                self.provider.upper(),
                self._last_error,
            )
            return self._last_decision

        with self._lock:
            self._last_decision = decision
            self._last_error = ""
            self._rl_attempts = 0
        log.info(
            "[%s] decision=%s signal=%s confidence=%.1f step=%.2f investment=%s levels=%s/%s",
            self.provider.upper(),
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
                "provider": self.provider,
                "required_for_auto_grid": self.required_for_auto_grid,
                "ready": decision is not None,
                "model": self.model,
                "last_error": self._last_error,
                "backoff_sec_left": round(
                    max(0.0, self._rl_backoff_until - time.monotonic()), 1
                ),
                "tpm_tokens_used": sum(tk for _, tk in self._tpm_events),
                "decision": decision,
            }
