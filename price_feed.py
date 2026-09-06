import os
import threading
import time

from cachetools import TTLCache

from core.config import Config
from http_client import SESSION as _HTTP


def _tc_headers() -> dict:
    key = os.getenv("TONCENTER_API_KEY", "")
    return {"X-API-Key": key} if key else {}


COINGECKO_IDS = {
    "TON": "the-open-network",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
}


class PriceFeed:
    """Real prices via free APIs (CoinGecko + DexScreener). Thread-safe TTL cache."""

    def __init__(self, ttl=4):
        self.ttl = ttl
        # TTLCache: thread-safe, auto-expiring, no manual lock management
        self._cache = TTLCache(maxsize=32, ttl=ttl)
        self._fetching = set()
        self._fetch_lock = threading.Lock()

    def get(self, base, max_stale=None):
        base = (base or "").upper()
        now = time.time()

        # Fast path: cache hit
        price = self._cache.get(base)
        if price is not None:
            return price

        # Cache stampede protection
        with self._fetch_lock:
            if base in self._fetching:
                return None
            self._fetching.add(base)

        try:
            price = self._fetch(base)
        finally:
            with self._fetch_lock:
                self._fetching.discard(base)

        if price and price > 0:
            self._cache[base] = price
            return price
        return None

    def _fetch(self, base):
        cid = COINGECKO_IDS.get(base)
        if cid:
            return self._fetch_coingecko(cid)
        token_symbol = (getattr(Config, "SYMBOL", "") or "").split("/")[0].upper()
        if base == token_symbol or base == "GRINCH":
            return self._fetch_dexscreener(Config.TOKEN_ADDRESS)
        return None

    def _fetch_coingecko(self, coin_id):
        try:
            r = _HTTP.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd"},
                timeout=10,
            )
            r.raise_for_status()
            return float(r.json()[coin_id]["usd"])
        except Exception:
            return None

    def _fetch_dexscreener(self, token_address):
        try:
            r = _HTTP.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
                timeout=10,
            )
            r.raise_for_status()
            pairs = r.json().get("pairs") or []
            if pairs:
                pairs.sort(
                    key=lambda p: (p.get("liquidity", {}) or {}).get("usd", 0),
                    reverse=True,
                )
                return float(pairs[0]["priceUsd"])
        except Exception:
            pass
        return None

    def get_token_ton_price(self, max_stale=None):
        key = "TOKEN_TON"
        price = self._cache.get(key)
        if price is not None:
            return price
        price = self._fetch_token_ton_native()
        if price and price > 0:
            self._cache[key] = price
            return price
        return None

    def _fetch_token_ton_native(self):
        onchain = self._fetch_token_ton_onchain()
        if onchain and onchain > 0:
            return onchain
        try:
            r = _HTTP.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{Config.TOKEN_ADDRESS}",
                timeout=10,
            )
            r.raise_for_status()
            pairs = r.json().get("pairs") or []
            if not pairs:
                return None
            pinned = (getattr(Config, "GRINCH_POOL_ADDRESS", "") or "").lower()
            if pinned:
                for p in pairs:
                    if (p.get("pairAddress", "") or "").lower() == pinned:
                        pn = p.get("priceNative")
                        if pn:
                            return float(pn)
            ton_pairs = [
                p
                for p in pairs
                if ((p.get("quoteToken", {}) or {}).get("symbol", "") or "").upper()
                == "TON"
                and p.get("priceNative")
            ]
            if not ton_pairs:
                return None
            ton_pairs.sort(
                key=lambda p: (p.get("liquidity", {}) or {}).get("usd", 0),
                reverse=True,
            )
            return float(ton_pairs[0]["priceNative"])
        except Exception:
            return None

    def _fetch_token_ton_onchain(self):
        try:
            pool = Config.POOL_ADDRESS
            r = _HTTP.post(
                "https://toncenter.com/api/v2/runGetMethod",
                json={"address": pool, "method": "get_pool_data", "stack": []},
                headers={"Accept": "application/json", **_tc_headers()},
                timeout=8,
            )
            d = r.json()
            res = d.get("result") or {}
            if not d.get("ok") or res.get("exit_code") not in (0, None):
                return None
            stack = res.get("stack") or []
            if len(stack) < 11 or stack[9][0] != "num" or stack[10][0] != "num":
                return None
            ton_reserve = int(stack[9][1], 16) / 1e9
            grinch_reserve = int(stack[10][1], 16) / 1e9
            if ton_reserve > 0 and grinch_reserve > 0:
                price = ton_reserve / grinch_reserve
                if 1e-6 < price < 1e-1:
                    return price
        except Exception:
            return None
        return None


price_feed = PriceFeed()


def _start_price_prefetch():
    import concurrent.futures

    _executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="price-pf"
    )

    def _warm():
        try:
            f1 = _executor.submit(price_feed.get, "GRINCH")
            f2 = _executor.submit(price_feed.get, "TON")
            f3 = _executor.submit(price_feed.get_token_ton_price)
            concurrent.futures.wait([f1, f2, f3], timeout=5)
        except Exception:
            pass

    def _loop():
        while True:
            _warm()
            threading.Event().wait(timeout=3)

    t = threading.Thread(target=_loop, name="price-prefetch", daemon=True)
    t.start()
