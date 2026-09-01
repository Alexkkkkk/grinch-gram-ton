"""price_feed_real.py — Gram (ex-Toncoin) / USD price feed.

Gram = rebranded native TON (June 2026), 1:10 split.
Verified sources (all return ~$1.39-1.40):
  1. MEXC:    api.mexc.com/api/v3/ticker/price?symbol=GRAMUSDT
  2. Gate.io: api.gateio.ws/api/v4/spot/tickers?currency_pair=GRAM_USDT
  3. LBank:   api.lbank.info/v2/ticker.do?symbol=gram_usdt

CoinGecko fallback REMOVED — it returns old TON price (~$3.50),
not Gram (~$1.40), because CoinGecko hasn't updated for the 1:10 split.
"""

import logging
import threading
import time
from collections import deque
from typing import Callable, Dict, List, Optional

_price_callbacks: List[Callable[[float], None]] = []


def register_price_callback(cb: Callable[[float], None]) -> None:
    if cb not in _price_callbacks:
        _price_callbacks.append(cb)


def unregister_price_callback(cb: Callable[[float], None]) -> None:
    if cb in _price_callbacks:
        _price_callbacks.remove(cb)


try:
    import requests
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger("price_feed_real")

_candles: deque = deque(maxlen=500)
_candles_cache: Dict[str, deque] = {}
_tick_history: deque = deque(maxlen=50000)  # ~28h at 2s intervals
_current_price: float = 0.0
_price_change_24h: float = 0.0
_lock = threading.RLock()
_last_fetch: float = 0.0
_bg_thread: Optional[threading.Thread] = None
_last_source: str = ""
_last_feed_error: str = ""
_external_candles_cache: Dict[str, List[dict]] = {}
_external_candles_fetched_at: Dict[str, float] = {}
_EXTERNAL_CANDLE_TTL = 3.0
# MEXC does not provide every timeframe shown by the dashboard. Unsupported
# timeframes are built from real lower-timeframe OHLCV rows below; never use
# generated/random candles as a fallback.
_MEXC_KLINE_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "4h": "4h",
    "1d": "1d",
    "1w": "1W",
}
_AGGREGATED_TIMEFRAMES = {
    "3m": ("1m", 3),
    "1h": ("15m", 4),
    "2h": ("15m", 8),
    "6h": ("15m", 24),
}

_TF_SECONDS = {
    "1s": 1,
    "1c": 1,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "1d": 86400,
    "1w": 604800,
}

# ═══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker integration for API resilience
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from circuit_breaker import CircuitBreaker

    _mexc_breaker = CircuitBreaker("mexc", failure_threshold=3, recovery_timeout=30)
    _gateio_breaker = CircuitBreaker("gateio", failure_threshold=3, recovery_timeout=30)
    _lbank_breaker = CircuitBreaker("lbank", failure_threshold=3, recovery_timeout=30)
except ImportError:
    _mexc_breaker = None
    _gateio_breaker = None
    _lbank_breaker = None


def _fetch_mexc_price() -> Optional[float]:
    """Primary: MEXC GRAMUSDT (verified $1.404)."""
    if requests is None:
        return None
    try:
        if _mexc_breaker and _mexc_breaker.state.value == "open":
            logger.debug("MEXC circuit OPEN — skipping")
            return None
        r = requests.get(
            "https://api.mexc.com/api/v3/ticker/price?symbol=GRAMUSDT",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code == 200:
            price = float(r.json().get("price", 0))
            if price > 0.5:
                if _mexc_breaker:
                    _mexc_breaker.record_success()
                logger.info("[MEXC] GRAM/USDT = $%.4f", price)
                return price
    except Exception as e:
        logger.debug("MEXC error: %s", e)
        if _mexc_breaker:
            _mexc_breaker.record_failure()
    return None


def _fetch_gateio_price() -> Optional[float]:
    """Backup 1: Gate.io GRAM_USDT (verified $1.3924)."""
    if requests is None:
        return None
    try:
        if _gateio_breaker and _gateio_breaker.state.value == "open":
            logger.debug("Gate.io circuit OPEN — skipping")
            return None
        r = requests.get(
            "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=GRAM_USDT",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                price = float(data[0].get("last", 0))
                if price > 0.5:
                    if _gateio_breaker:
                        _gateio_breaker.record_success()
                    logger.info("[Gate.io] GRAM/USDT = $%.4f", price)
                    return price
    except Exception as e:
        logger.debug("Gate.io error: %s", e)
        if _gateio_breaker:
            _gateio_breaker.record_failure()
    return None


def _fetch_lbank_price() -> Optional[float]:
    """Backup 2: LBank gram_usdt (verified ~$1.39)."""
    if requests is None:
        return None
    try:
        if _lbank_breaker and _lbank_breaker.state.value == "open":
            logger.debug("LBank circuit OPEN — skipping")
            return None
        r = requests.get(
            "https://api.lbank.info/v2/ticker.do?symbol=gram_usdt",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code == 200:
            ticker = r.json().get("data", [{}])[0].get("ticker", {})
            price = float(ticker.get("latest", 0))
            if price > 0.5:
                if _lbank_breaker:
                    _lbank_breaker.record_success()
                logger.info("[LBank] GRAM/USDT = $%.4f", price)
                return price
    except Exception as e:
        logger.debug("LBank error: %s", e)
        if _lbank_breaker:
            _lbank_breaker.record_failure()
    return None


def update_price() -> float:
    """Fetch the latest real market price without inventing a fallback value."""
    global _last_source, _last_feed_error

    sources = (
        ("MEXC", _fetch_mexc_price),
        ("Gate.io", _fetch_gateio_price),
        ("LBank", _fetch_lbank_price),
    )
    price = None
    source = ""
    errors = []
    for name, fetcher in sources:
        try:
            price = fetcher()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            price = None
        if price is not None and price >= 0.10:
            source = name
            break

    if price is None:
        with _lock:
            cached_price = _current_price
            cached_source = _last_source
        if cached_price > 0:
            price = cached_price
            source = f"{cached_source or 'exchange'} (stale)"
            logger.warning("All price APIs failed; keeping last real price $%.6f", price)
        else:
            _last_feed_error = "; ".join(errors) or "all market data sources unavailable"
            logger.error("No real market price available: %s", _last_feed_error)
            return 0.0

    with _lock:
        _last_source = source
        _last_feed_error = ""

    tick_price(price)

    for cb in _price_callbacks:
        try:
            cb(price)
        except Exception:  # nosec B110 — callback errors are non-critical
            logger.debug("Price callback error")

    return price


def get_feed_status() -> dict:
    """Expose freshness/source metadata for the dashboard without secrets."""
    with _lock:
        return {
            "source": _last_source or None,
            "last_update": _last_fetch or None,
            "stale": bool(_last_fetch and time.time() - _last_fetch > 30),
            "available": _current_price > 0,
            "error": _last_feed_error or None,
        }


def _fetch_mexc_candles_direct(timeframe: str, limit: int) -> List[dict]:
    """Fetch one of MEXC's natively supported real OHLCV intervals."""
    if requests is None:
        return []
    interval = _MEXC_KLINE_INTERVALS.get(timeframe)
    if not interval:
        return []
    try:
        response = requests.get(
            "https://api.mexc.com/api/v3/klines",
            params={
                "symbol": "GRAMUSDT",
                "interval": interval,
                "limit": min(max(int(limit), 1), 1000),
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        rows = response.json()
        candles = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                candles.append(
                    {
                        "t": int(row[0]) // 1000,
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
            except (TypeError, ValueError):
                continue
        return candles
    except Exception as exc:
        logger.warning("MEXC candles %s failed: %s", timeframe, exc)
        return []


def _aggregate_candles(
    candles: List[dict], timeframe: str, source_interval: str
) -> List[dict]:
    """Aggregate real exchange candles into a dashboard timeframe."""
    spec = _AGGREGATED_TIMEFRAMES.get(timeframe)
    source_seconds = _TF_SECONDS.get(source_interval)
    if not spec or not source_seconds or not candles:
        return []

    interval_seconds = _TF_SECONDS[timeframe]
    buckets: Dict[int, dict] = {}
    for candle in candles:
        timestamp = int(candle["t"])
        bucket_time = (timestamp // interval_seconds) * interval_seconds
        current = buckets.get(bucket_time)
        if current is None:
            buckets[bucket_time] = {
                "t": bucket_time,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle.get("volume", 0),
            }
            continue
        current["high"] = max(current["high"], candle["high"])
        current["low"] = min(current["low"], candle["low"])
        current["close"] = candle["close"]
        current["volume"] += candle.get("volume", 0)
    return [buckets[key] for key in sorted(buckets)]


def _fetch_mexc_candles(timeframe: str, limit: int) -> List[dict]:
    """Fetch real candles, aggregating only from real exchange OHLCV data."""
    if timeframe in _MEXC_KLINE_INTERVALS:
        return _fetch_mexc_candles_direct(timeframe, limit)

    source = _AGGREGATED_TIMEFRAMES.get(timeframe)
    if not source:
        return []
    source_interval, multiplier = source
    # Request enough real source rows for the requested number of output bars.
    source_limit = min(max(int(limit), 1) * multiplier, 1000)
    source_candles = _fetch_mexc_candles_direct(source_interval, source_limit)
    return _aggregate_candles(source_candles, timeframe, source_interval)


def _merge_live_price(candles: List[dict], timeframe: str) -> List[dict]:
    """Update only the still-open exchange candle with the latest real ticker."""
    if not candles:
        return candles
    with _lock:
        price = _current_price
    if price <= 0:
        return candles
    seconds = _TF_SECONDS.get(timeframe, 300)
    current_bucket = int(time.time() / seconds) * seconds
    last = candles[-1]
    if last.get("t") == current_bucket:
        last["high"] = max(last["high"], price)
        last["low"] = min(last["low"], price)
        last["close"] = price
    return candles


def _build_candles_for_interval(ticks: List[dict], interval_sec: int) -> List[dict]:
    """Build OHLCV candles from ticks for a given interval."""
    if len(ticks) < 1:
        return []
    buckets: Dict[int, List[dict]] = {}
    for t in ticks:
        bucket = int(t["t"] / interval_sec) * interval_sec
        buckets.setdefault(bucket, []).append(t)
    new_candles = []
    for bucket_ts in sorted(buckets.keys()):
        bucket = buckets[bucket_ts]
        prices = [b["price"] for b in bucket]
        new_candles.append(
            {
                "t": bucket_ts,
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
                "volume": sum(b.get("volume", 0) for b in bucket),
            }
        )
    return new_candles


_last_processed_tick_time: float = 0.0


def _build_candles_from_ticks():
    global _candles, _candles_cache, _last_processed_tick_time
    with _lock:
        ticks = list(_tick_history)
    if len(ticks) < 1:
        return
    # Only process ticks newer than last processed
    new_ticks = [t for t in ticks if t["t"] > _last_processed_tick_time]
    if not new_ticks:
        return
    _last_processed_tick_time = ticks[-1]["t"]
    # Build base 1-minute candles, plus genuine one-second candles from the
    # local tick stream for the dashboard's 1s timeframe.
    base_candles = _build_candles_for_interval(ticks, 60)
    with _lock:
        _candles.clear()
        for c in base_candles[-500:]:
            _candles.append(c)
        # Pre-build each timeframe at its actual interval. In particular, do
        # not substitute minute candles for the 1s view.
        for tf, sec in _TF_SECONDS.items():
            built = _build_candles_for_interval(ticks, sec)
            _candles_cache[tf] = deque(built[-500:], maxlen=500)


def tick_price(price: float) -> bool:
    """Record a price tick without fetching from API. Returns True if recorded."""
    global _current_price, _last_fetch, _price_change_24h
    with _lock:
        now = time.time()
        # Only record if price changed (avoids flat candles)
        if _tick_history and abs(_tick_history[-1]["price"] - price) < 0.0001:
            # The quote is unchanged, but the successful poll still refreshes freshness.
            _current_price = price
            _last_fetch = now
            return False
        _current_price = price
        _last_fetch = now
        _tick_history.append({"t": now, "price": price, "volume": 0})
        old = [t for t in _tick_history if t["t"] > now - 86400]
        if len(old) > 10:
            _price_change_24h = (price - old[0]["price"]) / old[0]["price"] * 100
    _build_candles_from_ticks()
    return True


def start_background_updates(interval: float = 10.0) -> None:
    """Start background thread to fetch fresh prices from APIs."""
    global _bg_thread
    if _bg_thread is not None and _bg_thread.is_alive():
        return

    def _loop():
        while True:
            try:
                update_price()
            except Exception:
                pass
            time.sleep(interval)

    _bg_thread = threading.Thread(target=_loop, daemon=True)
    _bg_thread.start()
    logger.info("[PriceFeed] Background updates started (interval=%.1fs)", interval)


def get_current_price() -> float:
    with _lock:
        stale = (time.time() - _last_fetch) > 30
        price = _current_price
    if stale or price == 0:
        return update_price()
    return price


def get_price_change_24h() -> float:
    return _price_change_24h


def fetch_external_candles(timeframe: str = "15m", limit: int = 200) -> List[dict]:
    return get_candles_timeframe(timeframe, limit)


def get_candles_timeframe(timeframe: str = "5m", limit: int = 200) -> List[dict]:
    """Return real exchange OHLCV candles, with a live update to the open bar."""
    tf = normalize_timeframe(timeframe)
    safe_limit = min(max(int(limit or 200), 1), 1000)
    now = time.time()

    if tf in _MEXC_KLINE_INTERVALS or tf in _AGGREGATED_TIMEFRAMES:
        with _lock:
            cached = _external_candles_cache.get(tf)
            fetched_at = _external_candles_fetched_at.get(tf, 0.0)
        if not cached or now - fetched_at >= _EXTERNAL_CANDLE_TTL:
            fresh = _fetch_mexc_candles(tf, max(safe_limit, 300))
            if fresh:
                with _lock:
                    _external_candles_cache[tf] = fresh
                    _external_candles_fetched_at[tf] = now
                cached = fresh
        if cached:
            return _merge_live_price(list(cached[-safe_limit:]), tf)

    # Only real local ticker history is allowed as a fallback. Never fabricate candles.
    with _lock:
        return list(_candles_cache.get(tf, _candles))[-safe_limit:]


def get_price_history(limit: int = 100) -> List[dict]:
    with _lock:
        return list(_tick_history)[-limit:]


def get_candles() -> List[dict]:
    return get_candles_timeframe("5m", 200)


# Backward-compatible helpers used by the existing API routes.
def normalize_timeframe(timeframe: str = "5m") -> str:
    """Normalize chart timeframe aliases to supported timeframe keys."""
    aliases = {
        "1c": "1s",
        "1sec": "1s",
        "1сек": "1s",
        "1с": "1s",
        "1min": "1m",
        "3min": "3m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "1hour": "1h",
        "2hour": "2h",
        "4hour": "4h",
        "6hour": "6h",
        "day": "1d",
        "week": "1w",
        "1мин": "1m",
        "3мин": "3m",
        "5мин": "5m",
        "15мин": "15m",
        "30мин": "30m",
        "1ч": "1h",
        "2ч": "2h",
        "4ч": "4h",
        "6ч": "6h",
        "день": "1d",
        "неделя": "1w",
    }
    value = str(timeframe or "5m").strip()
    return aliases.get(value.lower(), value)


def get_history_for_chart(hours: int = 24) -> dict:
    """Return real exchange price history for the dashboard chart."""
    cutoff = time.time() - hours * 3600
    requested = min(max(int(hours or 24) * 60, 100), 1000)
    candles = [c for c in get_candles_timeframe("1m", requested) if c["t"] > cutoff]
    prices = [{"t": c["t"], "price": c["close"]} for c in candles]
    pnls = []
    pnl = 0.0
    for candle in candles:
        opening = candle.get("open", 0)
        change = (candle["close"] - opening) / opening if opening > 0 else 0
        pnl += change * 100
        pnls.append({"t": candle["t"], "pnl": round(pnl, 4), "price": candle["close"]})
    return {
        "prices": prices,
        "pnl": pnls,
        "price_count": len(prices),
        "pnl_count": len(pnls),
    }
