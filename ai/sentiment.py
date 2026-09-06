"""
sentiment.py v1 — QuantumSentiment: Анализ настроений рынка TON/USDT.

Источники:
  1. On-Chain Order Flow   — дельта покупок/продаж через DeDust volume
  2. Volume Anomaly        — детекция аномальных объёмов (Z-score)
  3. Momentum Divergence   — расхождение цены и объёма
  4. Liquidation Proxy     — экстремальные движения как прокси ликвидаций
  5. Social Pulse          — опциональный сентимент через CoinGecko/CMC
  6. Fear & Greed Index    — композитный индекс 0-100

Выход: sentiment_score (-1..+1), conviction (0..1), regime_label
"""

import logging
import os
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from typing import List, Optional, Tuple

import numpy as np
import requests

logger = logging.getLogger("sentiment")

# ── Константы ────────────────────────────────────────────────────────────────
SENTIMENT_WINDOW = 100  # свечей для расчёта
VOLUME_Z_THRESHOLD = 2.5  # Z-score для аномалии объёма
FEAR_GREED_SMOOTHING = 0.3  # EMA smoothing для индекса


class OrderFlowAnalyzer:
    """Анализирует дельту покупок/продаж через свечи."""

    def __init__(self, window: int = 20):
        self._window = window
        self._buy_pressure: deque = deque(maxlen=window)
        self._sell_pressure: deque = deque(maxlen=window)

    def feed(self, candle: dict):
        """
        Оцениваем направление объёма через close-location:
        close ближе к high → покупки доминируют
        close ближе к low → продажи доминируют
        """
        o = float(candle.get("open", candle.get("o", 0)))
        h = float(candle.get("high", candle.get("h", 0)))
        l = float(candle.get("low", candle.get("l", 0)))
        c = float(candle.get("close", candle.get("c", 0)))
        v = float(candle.get("volume", candle.get("v", 0)))

        if h == l or v <= 0:
            return

        # Close location value: 0=low, 1=high
        clv = (c - l) / (h - l)
        # Нормализуем: 0.5 = нейтрально
        buy_vol = v * clv
        sell_vol = v * (1 - clv)

        self._buy_pressure.append(buy_vol)
        self._sell_pressure.append(sell_vol)

    def get_delta(self) -> Tuple[float, float]:
        """Вернуть (delta_ratio, confidence)."""
        if len(self._buy_pressure) < 5:
            return 0.0, 0.0
        total_buy = sum(self._buy_pressure)
        total_sell = sum(self._sell_pressure)
        total = total_buy + total_sell
        if total < 1e-9:
            return 0.0, 0.0
        delta = (total_buy - total_sell) / total
        # Уверенность растёт с объёмом данных
        confidence = min(1.0, len(self._buy_pressure) / self._window)
        return delta, confidence


class VolumeAnomalyDetector:
    """Детектирует аномальные объёмы через Z-score."""

    def __init__(self, window: int = 50):
        self._window = window
        self._volumes: deque = deque(maxlen=window)

    def feed(self, volume: float):
        self._volumes.append(volume)

    def is_anomaly(self, current_volume: float) -> Tuple[bool, float, float]:
        """Вернуть (is_anomaly, z_score, percentile)."""
        if len(self._volumes) < 10:
            return False, 0.0, 0.5
        arr = np.array(self._volumes)
        mean = np.mean(arr)
        std = np.std(arr) + 1e-9
        z = (current_volume - mean) / std
        percentile = sum(1 for v in self._volumes if v < current_volume) / len(
            self._volumes
        )
        return abs(z) > VOLUME_Z_THRESHOLD, z, percentile


class MomentumDivergence:
    """Детектирует расхождение цены и объёма (bearish/bullish divergence)."""

    def __init__(self, window: int = 14):
        self._window = window
        self._prices: deque = deque(maxlen=window * 2)
        self._volumes: deque = deque(maxlen=window * 2)

    def feed(self, price: float, volume: float):
        self._prices.append(price)
        self._volumes.append(volume)

    def check_divergence(self) -> Tuple[str, float]:
        """
        Вернуть (type, strength):
        type: "bullish_div", "bearish_div", "none"
        """
        if len(self._prices) < self._window * 2:
            return "none", 0.0

        p = list(self._prices)
        v = list(self._volumes)
        half = len(p) // 2

        # Первая половина
        p1_min, p1_max = min(p[:half]), max(p[:half])
        v1_max = max(v[:half])
        # Вторая половина
        p2_min, p2_max = min(p[half:]), max(p[half:])
        v2_max = max(v[half:])

        # Bullish: цена ниже, объём выше (накапливание)
        if p2_min < p1_min and v2_max > v1_max * 1.2:
            strength = (v2_max / max(v1_max, 1e-9) - 1) * (
                p1_min / max(p2_min, 1e-9) - 1
            )
            return "bullish_div", min(1.0, strength)

        # Bearish: цена выше, объём ниже (истощение)
        if p2_max > p1_max and v2_max < v1_max * 0.8:
            strength = (p2_max / max(p1_max, 1e-9) - 1) * (
                1 - v2_max / max(v1_max, 1e-9)
            )
            return "bearish_div", min(1.0, strength)

        return "none", 0.0


class LiquidationProxy:
    """
    Прокси для ликвидаций: экстремальные движения цены с высоким объёмом
    указывают на ликвидации (особенно в DeFi без маржинальной торговли —
    это скорее panic selling / FOMO buying).
    """

    def __init__(self, window: int = 20):
        self._window = window
        self._returns: deque = deque(maxlen=window)
        self._volumes: deque = deque(maxlen=window)

    def feed(self, price: float, prev_price: float, volume: float):
        ret = abs((price - prev_price) / (prev_price + 1e-9)) * 100
        self._returns.append(ret)
        self._volumes.append(volume)

    def detect(self) -> Tuple[str, float]:
        """Вернуть (event_type, severity_0_1)."""
        if len(self._returns) < 10:
            return "calm", 0.0

        recent_ret = np.mean(list(self._returns)[-5:])
        recent_vol = np.mean(list(self._volumes)[-5:])
        hist_vol = (
            np.mean(list(self._volumes)[:-5]) if len(self._volumes) > 5 else recent_vol
        )

        if recent_ret > 5.0 and recent_vol > hist_vol * 2:
            return "panic_spike", min(1.0, recent_ret / 15.0)
        if recent_ret > 3.0 and recent_vol > hist_vol * 1.5:
            return "high_activity", min(1.0, recent_ret / 10.0)
        return "calm", 0.0


class FearGreedIndex:
    """
    Композитный индекс страха и жадности (0=Extreme Fear, 100=Extreme Greed).
    Адаптирован для DeDust / DEX без маржинальной торговли.
    """

    def __init__(self):
        self._value = 50.0
        self._history: deque = deque(maxlen=50)

    def update(self, metrics: dict):
        """
        metrics: {
            "price_change_24h": float,  # % изменения за 24ч
            "volume_ratio": float,      # текущий объём / средний
            "order_flow_delta": float,  # -1..+1
            "volatility_ratio": float,  # текущая волатильность / средняя
            "divergence": str,          # "bullish_div", "bearish_div", "none"
            "divergence_strength": float,
        }
        """
        score = 50.0

        # 1. Price momentum (0-25 points)
        pc = metrics.get("price_change_24h", 0)
        score += max(-25, min(25, pc * 2))

        # 2. Volume (0-15 points) — высокий объём на росте = жадность
        vr = metrics.get("volume_ratio", 1.0)
        if pc > 0:
            score += max(-15, min(15, (vr - 1) * 15))
        else:
            score -= max(-15, min(15, (vr - 1) * 15))

        # 3. Order flow (0-20 points)
        of = metrics.get("order_flow_delta", 0)
        score += max(-20, min(20, of * 20))

        # 4. Volatility (0-15 points) — экстремальная волатильность = страх
        vol_r = metrics.get("volatility_ratio", 1.0)
        if vol_r > 2.0:
            score -= min(15, (vol_r - 1) * 10)

        # 5. Divergence (0-15 points)
        div = metrics.get("divergence", "none")
        div_s = metrics.get("divergence_strength", 0)
        if div == "bullish_div":
            score += min(15, div_s * 15)
        elif div == "bearish_div":
            score -= min(15, div_s * 15)

        # Smooth
        self._value = (
            self._value * (1 - FEAR_GREED_SMOOTHING) + score * FEAR_GREED_SMOOTHING
        )
        self._value = max(0, min(100, self._value))
        self._history.append(self._value)

    @property
    def value(self) -> float:
        return round(self._value, 2)

    @property
    def label(self) -> str:
        v = self._value
        if v >= 75:
            return "Extreme Greed"
        if v >= 55:
            return "Greed"
        if v >= 45:
            return "Neutral"
        if v >= 25:
            return "Fear"
        return "Extreme Fear"

    @property
    def sentiment_score(self) -> float:
        """Нормализованный сентимент -1..+1."""
        return (self._value - 50) / 50

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "label": self.label,
            "sentiment_score": round(self.sentiment_score, 4),
            "history": list(self._history)[-20:],
        }


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


# RSS-ленты крипто-новостей (без API-ключей, fail-closed)
_NEWS_FEEDS = (
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
)
_NEWS_TIMEOUT = 8.0
_LLM_TIMEOUT = 25.0
_LLM_NEWS_TTL = 900.0  # 15 минут кэш
_LLM_NEWS_WEIGHT = 0.25  # вклад LLM в итоговый сентимент
_LLM_MAX_HEADLINES = 25


class LLMNewsSentiment:
    """Новостной сентимент через локальную LLM (Ollama/llamafile).

    Берёт заголовки из публичных RSS-лент и просит локальную модель оценить
    рыночный настрой. Полностью опционален: любая ошибка сети, парсинга или
    недоступность LLM даёт нейтральный результат без влияния на сигнал.
    """

    def __init__(self):
        # Приоритет провайдеров — как в kimi_grid_control:
        # облако (groq/kimi) с реальным ключом, затем локальные (llamafile/ollama).
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        kimi_key = os.getenv("MOONSHOT_API_KEY", "").strip()
        llamafile_url = os.getenv("LLAMAFILE_BASE_URL", "").strip()
        ollama_url = os.getenv("OLLAMA_BASE_URL", "").strip()
        if groq_key:
            self.provider = "groq"
            self.base_url = "https://api.groq.com/openai/v1"
            self._api_key = groq_key
        elif kimi_key:
            self.provider = "kimi"
            self.base_url = "https://api.moonshot.ai/v1"
            self._api_key = kimi_key
        elif llamafile_url:
            self.provider = "llamafile"
            self.base_url = llamafile_url.rstrip("/")
            self._api_key = ""
        elif ollama_url or _bool_env("OLLAMA_ENABLED", False):
            self.provider = "ollama"
            self.base_url = (ollama_url or "http://127.0.0.1:11434/v1").rstrip("/")
            self._api_key = ""
        else:
            self.provider = "none"
            self.base_url = ""
            self._api_key = ""
        _model_defaults = {
            "groq": "llama-3.1-8b-instant",
            "kimi": "kimi-k2.6",
            "ollama": "llama3.1:8b",
            "llamafile": "llamafile",
        }
        prefix = self.provider.upper()
        self.model = (
            os.getenv("LLM_NEWS_MODEL", "").strip()
            or os.getenv(f"{prefix}_MODEL", "").strip()
            or _model_defaults.get(self.provider, "llama3.1:8b")
        )
        self.enabled = self.provider != "none" and _bool_env("LLM_NEWS_ENABLED", True)
        self._cache: Optional[dict] = None
        self._fetched_at = 0.0
        self._lock = threading.Lock()
        self._fetching = False
        self._last_error = ""

    # ── Загрузка заголовков ─────────────────────────────────────────────

    def _fetch_headlines(self) -> List[str]:
        headers = {"User-Agent": "QuantumGrinch/7 (+local sentiment)"}
        titles: List[str] = []
        for feed in _NEWS_FEEDS:
            try:
                resp = requests.get(feed, headers=headers, timeout=_NEWS_TIMEOUT)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                for item in root.iter("item"):
                    title = (item.findtext("title") or "").strip()
                    if title:
                        titles.append(title)
                    if len(titles) >= _LLM_MAX_HEADLINES:
                        return titles
            except Exception as exc:
                logger.warning("[llm-news] feed %s unavailable: %s", feed, exc)
        return titles[:_LLM_MAX_HEADLINES]

    # ── Оценка LLM ──────────────────────────────────────────────────────

    def _score(self, headlines: List[str]) -> Optional[dict]:
        if not self.base_url:
            return None
        system = (
            "You are a crypto market sentiment analyst. Based ONLY on the "
            "news headlines provided, estimate the short-term market mood "
            "for TON (Toncoin). Reply with JSON only, exactly these keys: "
            'score (float -1.0 very bearish .. +1.0 very bullish), '
            'confidence (float 0..1), summary (short string, max 12 words). '
            "No markdown, no extra keys."
        )
        user = "Headlines:\n" + "\n".join(f"- {h}" for h in headlines)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "stream": False,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=_LLM_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}"
            logger.warning("[llm-news] LLM request failed: %s", exc)
            return None

        text = str(content or "").strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            import json

            parsed = json.loads(text)
            score = max(-1.0, min(1.0, float(parsed.get("score", 0.0))))
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
            return {
                "score": round(score, 4),
                "confidence": round(confidence, 4),
                "summary": str(parsed.get("summary", ""))[:160],
                "headlines_used": len(headlines),
                "model": self.model,
            }
        except Exception as exc:
            self._last_error = f"parse:{type(exc).__name__}"
            logger.warning("[llm-news] cannot parse LLM response: %s", exc)
            return None

    # ── Публичное API ───────────────────────────────────────────────────

    def refresh(self):
        """Перезагрузить новости и оценку (блокирующий, вызывать из потока)."""
        if not self.enabled or self._fetching:
            return
        self._fetching = True
        try:
            headlines = self._fetch_headlines()
            if not headlines:
                return
            scored = self._score(headlines)
            if scored:
                with self._lock:
                    self._cache = scored
                    self._fetched_at = time.time()
                    self._last_error = ""
        finally:
            self._fetching = False

    def get(self) -> Optional[dict]:
        """Актуальный результат или None. Устаревший кэш запускает фоновое обновление."""
        if not self.enabled:
            return None
        with self._lock:
            cache = self._cache
            fetched_at = self._fetched_at
        if cache and (time.time() - fetched_at) < _LLM_NEWS_TTL:
            return cache
        if not self._fetching:
            threading.Thread(target=self.refresh, daemon=True).start()
        return cache  # None или чуть устаревший — вес снижается ниже

    def to_dict(self) -> dict:
        with self._lock:
            cache = dict(self._cache) if self._cache else None
            age = round(time.time() - self._fetched_at, 1) if self._fetched_at else None
        return {
            "enabled": self.enabled,
            "model": self.model,
            "base_url": self.base_url,
            "fresh": bool(cache and age is not None and age < _LLM_NEWS_TTL),
            "age_sec": age,
            "last_error": self._last_error,
            "result": cache,
        }


class QuantumSentiment:
    """Единый движок сентимента."""

    def __init__(self):
        self._order_flow = OrderFlowAnalyzer()
        self._volume_anomaly = VolumeAnomalyDetector()
        self._divergence = MomentumDivergence()
        self._liquidation = LiquidationProxy()
        self._fear_greed = FearGreedIndex()
        self._llm_news = LLMNewsSentiment()
        self._candles: deque = deque(maxlen=SENTIMENT_WINDOW)
        self._lock = threading.RLock()

    def feed_candles(self, candles: List[dict]):
        """Потоковое обновление по свечам."""
        with self._lock:
            for c in candles:
                self._candles.append(c)
                self._order_flow.feed(c)
                self._volume_anomaly.feed(float(c.get("volume", c.get("v", 0))))

                price = float(c.get("close", c.get("c", 0)))
                vol = float(c.get("volume", c.get("v", 0)))
                if self._candles:
                    prev = list(self._candles)[-2] if len(self._candles) > 1 else c
                    prev_price = float(prev.get("close", prev.get("c", price)))
                    self._liquidation.feed(price, prev_price, vol)
                self._divergence.feed(price, vol)

    def analyze(self) -> dict:
        """Полный анализ сентимента."""
        with self._lock:
            if len(self._candles) < 10:
                return self._default_result()

            candles = list(self._candles)
            current = candles[-1]
            current_price = float(current.get("close", current.get("c", 0)))
            current_vol = float(current.get("volume", current.get("v", 0)))

            # Order flow
            of_delta, of_conf = self._order_flow.get_delta()

            # Volume anomaly
            is_anomaly, vol_z, vol_pct = self._volume_anomaly.is_anomaly(current_vol)

            # Divergence
            div_type, div_strength = self._divergence.check_divergence()

            # Liquidation proxy
            liq_event, liq_sev = self._liquidation.detect()

            # Price change 24h (прокси — последние N свечей)
            if len(candles) >= 24:
                price_24h_ago = float(
                    candles[-24].get("close", candles[-24].get("c", current_price))
                )
                price_change_24h = (
                    (current_price - price_24h_ago) / (price_24h_ago + 1e-9) * 100
                )
            else:
                price_change_24h = 0.0

            # Volatility ratio
            returns = []
            for i in range(1, len(candles)):
                p1 = float(candles[i - 1].get("close", candles[i - 1].get("c", 0)))
                p2 = float(candles[i].get("close", candles[i].get("c", 0)))
                returns.append(abs((p2 - p1) / (p1 + 1e-9)) * 100)
            recent_vol = np.mean(returns[-5:]) if len(returns) >= 5 else 0
            hist_vol = np.mean(returns[:-5]) if len(returns) > 5 else recent_vol
            vol_ratio = recent_vol / (hist_vol + 1e-9) if hist_vol > 0 else 1.0

            # Update Fear & Greed
            self._fear_greed.update(
                {
                    "price_change_24h": price_change_24h,
                    "volume_ratio": vol_ratio,
                    "order_flow_delta": of_delta,
                    "volatility_ratio": vol_ratio,
                    "divergence": div_type,
                    "divergence_strength": div_strength,
                }
            )

            # LLM-новостной сентимент (опционально, fail-closed)
            llm_news = self._llm_news.get()
            llm_fresh = bool(
                llm_news and (time.time() - getattr(self._llm_news, "_fetched_at", 0)) < _LLM_NEWS_TTL
            )

            # Итоговый сентимент
            sentiment = self._fear_greed.sentiment_score
            conviction = of_conf * 0.3 + (1.0 if is_anomaly else 0.5) * 0.2 + 0.5
            if llm_news:
                w = _LLM_NEWS_WEIGHT * (llm_news.get("confidence") or 0.0)
                if not llm_fresh:
                    w *= 0.5  # устаревший кэш вдвое менее значим
                sentiment = sentiment * (1 - w) + llm_news["score"] * w
                conviction = min(1.0, conviction + 0.1 * llm_news.get("confidence", 0.0))
            conviction = min(1.0, conviction)

            # Сигнал
            if sentiment > 0.3 and of_delta > 0.2:
                signal = "BULLISH"
            elif sentiment < -0.3 and of_delta < -0.2:
                signal = "BEARISH"
            elif is_anomaly and vol_z > 0:
                signal = "ACCUMULATION"
            elif is_anomaly and vol_z < 0:
                signal = "DISTRIBUTION"
            else:
                signal = "NEUTRAL"

            return {
                "signal": signal,
                "sentiment_score": round(sentiment, 4),
                "conviction": round(conviction, 4),
                "fear_greed": self._fear_greed.to_dict(),
                "order_flow_delta": round(of_delta, 4),
                "volume_anomaly": {
                    "is_anomaly": is_anomaly,
                    "z_score": round(vol_z, 4),
                    "percentile": round(vol_pct, 4),
                },
                "divergence": {"type": div_type, "strength": round(div_strength, 4)},
                "liquidation_proxy": {
                    "event": liq_event,
                    "severity": round(liq_sev, 4),
                },
                "price_change_24h": round(price_change_24h, 4),
                "volatility_ratio": round(vol_ratio, 4),
                "llm_news": {
                    "available": bool(llm_news),
                    "fresh": llm_fresh,
                    **(llm_news or {}),
                },
            }

    def _default_result(self) -> dict:
        return {
            "signal": "NEUTRAL",
            "sentiment_score": 0.0,
            "conviction": 0.0,
            "fear_greed": self._fear_greed.to_dict(),
            "order_flow_delta": 0.0,
            "volume_anomaly": {"is_anomaly": False, "z_score": 0.0, "percentile": 0.5},
            "divergence": {"type": "none", "strength": 0.0},
            "liquidation_proxy": {"event": "calm", "severity": 0.0},
            "price_change_24h": 0.0,
            "volatility_ratio": 1.0,
            "llm_news": {"available": False, "fresh": False},
        }

    def to_dict(self) -> dict:
        return self.analyze()


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════
_sentiment: Optional[QuantumSentiment] = None


def get_sentiment() -> QuantumSentiment:
    global _sentiment
    if _sentiment is None:
        _sentiment = QuantumSentiment()
    return _sentiment


def analyze(candles: List[dict]) -> dict:
    """Публичный API: проанализировать сентимент."""
    engine = get_sentiment()
    engine.feed_candles(candles)
    return engine.analyze()


def get_llm_news() -> Optional[dict]:
    """Свежий результат LLM-новостного сентимента (или None).

    Публичная точка доступа для советников (quantum_brain, brain_fusion):
    запускает фоновое обновление при устаревании кэша.
    """
    return get_sentiment()._llm_news.get()
