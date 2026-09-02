"""
DeDust DEX клиент для реальной торговли TON/USDT в блокчейне TON.
USDT = нативный TON (переименован в 2026).
Все блокчейн-операции асинхронные — запускаются через _run().
"""

import asyncio
import logging
import os
import secrets
import threading
import time
from typing import Optional

from dedust import (
    Asset,
    Factory,
    JettonRoot,
    Pool,
    PoolType,
    SwapParams,
    VaultJetton,
    VaultNative,
)
from pytoniq import Address, LiteBalancer, WalletV5R1
from pytoniq_core import Address as CoreAddress
from pytoniq_core import begin_cell

from core.config import Config
from http_client import SESSION as _HTTP
from price_feed import price_feed


def _tc_headers() -> dict:
    """Возвращает заголовки для TonCenter API (X-API-Key, если задан)."""
    key = os.getenv("TONCENTER_API_KEY", "")
    return {"X-API-Key": key} if key else {}


log = logging.getLogger(__name__)

# 1 TON = 1_000_000_000 нанотонов
TON = 1_000_000_000

# Адрес мастер-контракта DeDust Factory в мейннете
_FACTORY_ADDR = "EQBfBWT7X2BHg9tXAxzhz2aKiNTU1tSvKBUIB6mmAR0096nr"

# ── Глобальный кеш баланса (TTL 150 сек) — все модули читают отсюда ──────────
# Предотвращает шторм 429 от TonCenter: трейдер, ликвидатор, deposit monitor
# делают независимые запросы каждые 30–60 сек. Общий кеш сводит фактические
# HTTP-вызовы к одному раз в 150 секунд, независимо от числа читателей.
_BAL_CACHE: dict = {}  # {"TON": float, "USDT": float}
_BAL_CACHE_TS: float = 0.0  # timestamp последнего успешного обновления
_BAL_CACHE_TTL: float = 150.0  # секунды
_BAL_CACHE_LOCK = threading.Lock()
_BAL_BACKOFF_UNTIL: float = 0.0  # не стучать раньше этого timestamp при 429
# C4-fix: сериализуем HTTP-запросы к API баланса — только один поток
# одновременно делает fetch. Остальные ждут его результата (double-checked).
_BAL_FETCH_LOCK = threading.Lock()


def get_shared_balance(force: bool = False) -> dict:
    """Возвращает кешированный баланс {TON, USDT} из глобального кеша.

    force=True обновляет даже если TTL не истёк (используется после свопа).
    При 429-backoff возвращает последний известный кеш не долбя API.
    """
    now = time.time()

    # Если backoff ещё не истёк — возвращаем кеш без запроса
    if not force and now < _BAL_BACKOFF_UNTIL:
        with _BAL_CACHE_LOCK:
            return dict(_BAL_CACHE) if _BAL_CACHE else {}

    # Если кеш свежий — возвращаем без запроса (быстрый путь без fetch-lock)
    with _BAL_CACHE_LOCK:
        if not force and _BAL_CACHE and (now - _BAL_CACHE_TS) < _BAL_CACHE_TTL:
            return dict(_BAL_CACHE)

    # C4-fix: сериализуем fetch — только один поток стучит в API.
    # Остальные блокируются на _BAL_FETCH_LOCK и после разблокировки
    # находят свежий кеш во втором (double-checked) чтении.
    with _BAL_FETCH_LOCK:
        # Двойная проверка: пока мы ждали lock — другой поток уже обновил кеш
        now = time.time()
        with _BAL_CACHE_LOCK:
            if not force and _BAL_CACHE and (now - _BAL_CACHE_TS) < _BAL_CACHE_TTL:
                return dict(_BAL_CACHE)

        # Нужно обновить — делаем HTTP запросы
        return _fetch_balance_and_update(force, now)


def _fetch_balance_and_update(force: bool, now: float) -> dict:
    """Внутренняя функция: делает HTTP-запросы и обновляет кеш.
    Вызывается только из get_shared_balance под _BAL_FETCH_LOCK.
    """
    global _BAL_CACHE, _BAL_CACHE_TS, _BAL_BACKOFF_UNTIL
    wallet = Config.TON_WALLET
    token = getattr(Config, "USDT_TOKEN_ADDRESS", Config.TOKEN_ADDRESS)

    ton_val: Optional[float] = None
    usdt_val: float = 0.0
    hit_429 = False

    # TON balance: TonCenter v2 → TonAPI v2
    try:
        r = _HTTP.get(
            "https://toncenter.com/api/v2/getAddressBalance",
            params={"address": wallet},
            headers=_tc_headers(),
            timeout=8,
        )
        if r.status_code == 429:
            hit_429 = True
        elif r.status_code == 200:
            result = r.json().get("result")
            if result is not None:
                ton_val = float(result) / TON
    except Exception:
        pass

    if ton_val is None and not hit_429:
        try:
            r = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{wallet}",
                headers={"Accept": "application/json"},
                timeout=8,
            )
            if r.status_code == 429:
                hit_429 = True
            elif r.status_code == 200:
                bal = r.json().get("balance")
                if bal is not None:
                    ton_val = float(bal) / TON
        except Exception:
            pass

    # USDT balance: TonCenter v3 → TonAPI direct → TonAPI list
    # USDT decimals = 6
    if not hit_429:
        try:
            r = _HTTP.get(
                "https://toncenter.com/api/v3/jetton/wallets",
                params={"owner_address": wallet, "jetton_address": token, "limit": 1},
                headers=_tc_headers(),
                timeout=8,
            )
            if r.status_code == 429:
                hit_429 = True
            elif r.status_code == 200:
                wallets = r.json().get("jetton_wallets", [])
                if wallets:
                    bal = wallets[0].get("balance")
                    if bal is not None:
                        usdt_val = float(bal) / (10**Config.USDT_DECIMALS)
        except Exception:
            pass

    if usdt_val == 0.0 and not hit_429:
        try:
            r = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{wallet}/jettons/{token}",
                headers={"Accept": "application/json"},
                timeout=8,
            )
            if r.status_code == 429:
                hit_429 = True
            elif r.status_code == 200:
                bal = r.json().get("balance")
                if bal is not None:
                    usdt_val = float(bal) / (10**Config.USDT_DECIMALS)
        except Exception:
            pass

    if hit_429:
        # Применяем backoff: не долбим API 90 секунд после 429
        with _BAL_CACHE_LOCK:
            _BAL_BACKOFF_UNTIL = now + 90.0
            log.warning("[Balance] 429 от TonCenter/TonAPI — пауза 90с, возвращаем кеш")
            return dict(_BAL_CACHE) if _BAL_CACHE else {}

    # Защита от «битого» ответа API: TON=0 при ненулевом кеше = сбой API
    with _BAL_CACHE_LOCK:
        _prev_ton = _BAL_CACHE.get("TON")
    if ton_val == 0.0 and _prev_ton and _prev_ton > 0.05:
        log.warning(
            f"[Balance] Подозрительный ответ TON=0 (был {_prev_ton}) — "
            "игнорируем, используем предыдущее значение"
        )
        ton_val = None

    # Обновляем кеш только если получили хотя бы одно реальное значение
    if ton_val is not None or usdt_val > 0:
        new_cache: dict = {
            "TON": (
                round(ton_val, 6) if ton_val is not None else _BAL_CACHE.get("TON", 0.0)
            ),
            "USDT": round(usdt_val, 4),
        }
        with _BAL_CACHE_LOCK:
            _BAL_CACHE = new_cache
            _BAL_CACHE_TS = now
        return dict(new_cache)

    # Ничего не получили — возвращаем старый кеш (или {} при холодном старте)
    with _BAL_CACHE_LOCK:
        return dict(_BAL_CACHE) if _BAL_CACHE else {}


def _run(coro):
    """Запускает async-корутину синхронно в новом event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class DedustClient:
    """
    Синхронная обёртка над DeDust SDK для использования в Flask-приложении.

    Поддерживает:
    - Получение баланса TON и USDT
    - Оценку выхода свопа (цена без исполнения)
    - Своп TON → USDT (покупка)
    - Своп USDT → TON (продажа)
    """

    def __init__(self, mnemonic_override: str = None):
        self._lock = threading.Lock()
        self._mnemonic: list[str] = []
        self._ready = False
        self._error: Optional[str] = None
        self._last_price: Optional[float] = None

        mnemonic_raw = mnemonic_override or os.getenv("TON_MNEMONIC", "")
        if not mnemonic_raw:
            self._error = "TON_MNEMONIC не задан — DeDust-режим недоступен"
            log.warning(self._error)
            return

        words = mnemonic_raw.strip().split()
        # C3 fix: сразу стираем raw-строку мнемоники из локальной переменной
        mnemonic_raw = None  # noqa
        if len(words) not in (24,):
            self._error = f"Мнемоника должна содержать 24 слова, получено: {len(words)}"
            log.error(self._error)
            words = []  # scrub
            return

        self._mnemonic = words
        self._ready = True
        log.info("[DeDust] Клиент инициализирован ✓")

        # Если TON_WALLET не задан явно — выводим адрес из мнемоники в фоне.
        # Это нужно когда пользователь задал только TON_MNEMONIC (bothost.tech).
        # Без этого баланс проверяется против захардкоженного дефолт-адреса → 0.
        if not os.environ.get("TON_WALLET"):
            t = threading.Thread(target=self._derive_and_set_wallet_addr, daemon=True)
            t.start()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> Optional[str]:
        return self._error

    # ─────────────────────────────── helpers ───────────────────────────────

    def _derive_and_set_wallet_addr(self):
        """Выводит адрес кошелька из мнемоники и обновляет Config.TON_WALLET.

        Запускается в фоновом потоке при старте, если TON_WALLET не задан
        явно через переменную окружения. Без этого balance-check идёт против
        захардкоженного дефолт-адреса и всегда показывает 0.
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                wallet, provider = loop.run_until_complete(self._wallet_and_provider())
                raw = wallet.address.to_str(is_user_friendly=True, is_bounceable=False)
                addr = self._clean_addr_str(raw)
                loop.run_until_complete(provider.close_all())
            finally:
                loop.close()
                asyncio.set_event_loop(None)

            if addr and addr != Config.TON_WALLET:
                log.info(f"[DeDust] ✅ Адрес кошелька выведен из мнемоники: {addr}")
                Config.TON_WALLET = addr
                # Сбросить кеш баланса — он считался против неправильного адреса
                global _BAL_CACHE_TS, _BAL_CACHE
                with _BAL_CACHE_LOCK:
                    _BAL_CACHE = {}
                    _BAL_CACHE_TS = 0.0
            else:
                log.info(f"[DeDust] Адрес кошелька совпадает с Config: {addr}")
        except Exception as e:
            log.warning(f"[DeDust] Не удалось вывести адрес из мнемоники: {e}")

    async def _make_provider(self) -> LiteBalancer:
        """Создаёт LiteBalancer с retry — pytoniq иногда падает с KeyError в listener."""
        last_exc = None
        for attempt in range(3):
            provider = None
            try:
                provider = LiteBalancer.from_mainnet_config(trust_level=1, timeout=15)
                await provider.start_up()
                return provider
            except Exception as e:
                last_exc = e
                if isinstance(e, KeyError):
                    log.warning(
                        f"[DeDust] LiteClient KeyError на попытке {attempt+1}/3 — "
                        "перезапускаем провайдер"
                    )
                else:
                    log.warning(
                        f"[DeDust] _make_provider попытка {attempt+1}/3 провалилась: {e}"
                    )
                if provider is not None:
                    try:
                        await provider.close_all()
                    except Exception:
                        pass
                import asyncio as _aio

                await _aio.sleep(1)
        raise last_exc

    async def _wallet_and_provider(self):
        provider = await self._make_provider()
        # WalletV5R1 (W5) — версия кошелька TonKeeper пользователя; mainnet global_id = -239
        wallet = await WalletV5R1.from_mnemonic(
            provider=provider, mnemonics=self._mnemonic, network_global_id=-239
        )
        return wallet, provider

    # ─────────────────────────── balance ───────────────────────────────────

    def _get_ton_balance_http(self) -> Optional[float]:
        """TON баланс через HTTP. Приоритет: TonCenter v2 → TonAPI v2.
        НЕ использует liteserver — он даёт 'not provable' garbage значения.
        """
        wallet = Config.TON_WALLET
        try:
            r = _HTTP.get(
                "https://toncenter.com/api/v2/getAddressBalance",
                params={"address": wallet},
                headers=_tc_headers(),
                timeout=8,
            )
            result = r.json().get("result")
            if result is not None:
                return float(result) / TON
        except Exception as e:
            log.debug(f"[DeDust] TON balance TonCenter v2: {e}")
        try:
            r = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{wallet}",
                headers={"Accept": "application/json"},
                timeout=8,
            )
            bal = r.json().get("balance")
            if bal is not None:
                return float(bal) / TON
        except Exception as e:
            log.debug(f"[DeDust] TON balance TonAPI: {e}")
        return None

    def _get_usdt_balance_http(self) -> float:
        """USDT баланс через HTTP.
        Приоритет: TonCenter v3 → TonAPI прямой эндпоинт → TonAPI список (с нормализацией адреса).
        """
        wallet = Config.TON_WALLET
        token = getattr(Config, "USDT_TOKEN_ADDRESS", Config.TOKEN_ADDRESS)

        # 1. TonCenter v3 (jetton/wallets)
        try:
            r = _HTTP.get(
                "https://toncenter.com/api/v3/jetton/wallets",
                params={"owner_address": wallet, "jetton_address": token, "limit": 1},
                headers=_tc_headers(),
                timeout=8,
            )
            if r.status_code == 200:
                wallets = r.json().get("jetton_wallets", [])
                if wallets:
                    bal = wallets[0].get("balance")
                    if bal is not None:
                        return float(bal) / (10**Config.USDT_DECIMALS)
            else:
                log.warning(f"[DeDust] USDT balance TonCenter v3: HTTP {r.status_code}")
        except Exception as e:
            log.warning(f"[DeDust] USDT balance TonCenter v3: {e}")

        # 2. TonAPI прямой эндпоинт для конкретного жетона — без поиска по списку
        try:
            r = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{wallet}/jettons/{token}",
                headers={"Accept": "application/json"},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                bal = data.get("balance")
                if bal is not None:
                    return float(bal) / (10**Config.USDT_DECIMALS)
            else:
                log.warning(
                    f"[DeDust] USDT balance TonAPI direct: HTTP {r.status_code}"
                )
        except Exception as e:
            log.warning(f"[DeDust] USDT balance TonAPI direct: {e}")

        # 3. TonAPI список жетонов — нормализуем адреса через raw hex (как в ликвидаторе)
        try:
            r = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{wallet}/jettons",
                headers={"Accept": "application/json"},
                timeout=8,
            )
            if r.status_code == 200:

                def _norm(addr: str) -> str:
                    try:
                        from pytoniq_core import Address as _Addr

                        return (
                            _Addr(addr.strip()).to_str(is_user_friendly=False).lower()
                        )
                    except Exception:
                        return (addr.split(":", 1)[-1] if ":" in addr else addr).lower()

                token_raw = _norm(token)
                for b in r.json().get("balances", []):
                    jaddr = (b.get("jetton", {}) or {}).get("address", "")
                    if _norm(jaddr) == token_raw:
                        return float(b.get("balance", 0)) / (10**Config.USDT_DECIMALS)
        except Exception as e:
            log.warning(f"[DeDust] USDT balance TonAPI list: {e}")

        return 0.0

    async def _get_balance_async(self) -> dict:
        """Делегирует в get_balance() (HTTP-based). Оставлен для совместимости."""
        return self.get_balance()

    # ───────────── низкоуровневые балансы для проверки исполнения ─────────────

    @staticmethod
    def _clean_addr_str(addr) -> str:
        """Возвращает чистую строку адреса (EQ.../UQ... или 0:xxx).

        str(pytoniq_core.Address) возвращает 'Address<EQ...>' — этот формат
        TonCenter v3 не принимает (422). Метод извлекает чистый адрес.
        Если addr является объектом Address, использует to_str() напрямую,
        чтобы не зависеть от формата __str__.
        """
        try:
            import pytoniq_core as _ptc

            if isinstance(addr, _ptc.Address):
                return addr.to_str(is_user_friendly=True, is_bounceable=False)
        except Exception:
            pass
        s = str(addr)
        if s.startswith("Address<") and s.endswith(">"):
            return s[8:-1]
        return s

    def _usdt_jetton_wallet_addr_via_api(self, owner_addr_str: str) -> Optional[str]:
        """Получает реальный адрес USDT jetton-кошелька (надёжно, несколько источников).

        Порядок: TonCenter v3 (стабильный, без rate-limit) → TonAPI → None.
        SDK JettonRoot.get_wallet() намеренно исключён: при сбое liteserver он
        вычисляет адрес локально и для нестандартных jetton-контрактов (USDT)
        возвращает неверный адрес.
        """
        # ── TonCenter v3 (первичный) ─────────────────────────────────────────
        try:
            r = _HTTP.get(
                "https://toncenter.com/api/v3/jetton/wallets",
                params={
                    "owner_address": owner_addr_str,
                    "jetton_address": getattr(Config, "USDT_TOKEN_ADDRESS", Config.TOKEN_ADDRESS),
                    "limit": 1,
                },
                headers=_tc_headers(),
                timeout=8,
            )
            wallets = r.json().get("jetton_wallets", [])
            if wallets:
                addr = wallets[0].get("address", "")
                if addr:
                    return addr.lower()  # raw hex 0:xxxx
        except Exception as e:
            log.debug(f"[DeDust] jetton wallet TonCenter v3: {e}")

        # ── TonAPI (резервный) ───────────────────────────────────────────────
        try:
            r = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{owner_addr_str}/jettons",
                headers={"Accept": "application/json"},
                timeout=8,
            )
            for b in r.json().get("balances", []):
                jaddr = (b.get("jetton", {}) or {}).get("address", "")
                if self._same_addr(jaddr, Config.TOKEN_ADDRESS):
                    return (b.get("wallet_address") or {}).get("address")
        except Exception as e:
            log.debug(f"[DeDust] jetton wallet TonAPI: {e}")

        return None

    async def _usdt_balance_nano(self, provider, addr) -> int:
        """USDT-баланс кошелька в нанотокенах (0, если jetton-кошелёк не задеплоен).

        Порядок: TonCenter v3 (стабильный) → TonAPI → SDK liteserver.
        SDK исключён как первичный: возвращает неверный адрес jetton-кошелька
        для нестандартных jetton-контрактов при сбое liteserver.
        """
        addr_str = self._clean_addr_str(addr)

        # ── TonCenter v3 (первичный, надёжный) ──────────────────────────────
        try:
            r = _HTTP.get(
                "https://toncenter.com/api/v3/jetton/wallets",
                params={
                    "owner_address": addr_str,
                    "jetton_address": Config.TOKEN_ADDRESS,
                    "limit": 1,
                },
                headers=_tc_headers(),
                timeout=6,
            )
            wallets = r.json().get("jetton_wallets", [])
            if wallets:
                bal = wallets[0].get("balance")
                if bal is not None:
                    return int(bal)
        except Exception as e:
            log.debug(f"[DeDust] usdt balance TonCenter v3: {e}")

        # ── TonAPI (резервный) ───────────────────────────────────────────────
        try:
            r = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{addr_str}/jettons",
                headers={"Accept": "application/json"},
                timeout=5,
            )
            for b in r.json().get("balances", []):
                jaddr = (b.get("jetton", {}) or {}).get("address", "")
                if self._same_addr(
                    jaddr, getattr(Config, "USDT_TOKEN_ADDRESS", Config.TOKEN_ADDRESS)
                ):
                    return int(b.get("balance", 0))
        except Exception as e:
            log.debug(f"[DeDust] usdt balance TonAPI: {e}")

        # ── SDK liteserver (последний резерв) ───────────────────────────────
        try:
            usdt_root = JettonRoot.create_from_address(
                getattr(Config, "USDT_TOKEN_ADDRESS", Config.TOKEN_ADDRESS)
            )
            gw = await usdt_root.get_wallet(addr, provider)
            g_state = await provider.get_account_state(gw.address)
            if getattr(g_state, "state", None) and g_state.state.type_ == "active":
                return await gw.get_balance(provider)
        except Exception as e:
            log.debug(f"[DeDust] usdt balance SDK: {e}")
        return 0

    async def _ensure_wallet_deployed(self, wallet, provider) -> bool:
        """Проверяет и при необходимости деплоит кошелёк WalletV5R1 на блокчейне.

        Возвращает True если кошелёк активен (или успешно задеплоен),
        False если деплой не удался или кошелёк заморожен.

        Вызывать ПЕРЕД wallet.transfer() — иначе seqno-вызов падает с exit_code=-256
        для uninit-кошелька (нет кода на чейне).
        """
        try:
            state = await provider.get_account_state(wallet.address)
            state_type = getattr(getattr(state, "state", None), "type_", None)
            if state_type == "active":
                return True  # уже задеплоен

            # uninit или frozen — пробуем задеплоить
            log.warning(
                f"[DeDust] 🚀 Кошелёк {wallet.address} не инициализирован "
                f"(state={state_type}). Отправляем deploy транзакцию..."
            )
            try:
                await wallet.deploy_via_external()
            except Exception as deploy_err:
                # deploy_via_external может отсутствовать в старых версиях
                try:
                    await wallet.send_init_external()
                except Exception as init_err:
                    log.error(
                        f"[DeDust] deploy failed: deploy_via_external={deploy_err} "
                        f"send_init_external={init_err}"
                    )
                    return False

            # Ждём подтверждения деплоя на чейне (до 45 сек)
            log.info("[DeDust] ⏳ Ожидаем активации кошелька на блокчейне...")
            for _ in range(9):
                await asyncio.sleep(5)
                try:
                    st2 = await provider.get_account_state(wallet.address)
                    if getattr(getattr(st2, "state", None), "type_", None) == "active":
                        log.info("[DeDust] ✅ Кошелёк задеплоен и активен!")
                        return True
                except Exception:
                    pass

            log.error("[DeDust] ❌ Кошелёк не стал активным за 45 сек после деплоя")
            return False

        except Exception as e:
            log.warning(f"[DeDust] _ensure_wallet_deployed ошибка: {e}")
            return False

    async def _wait_for_settlement(
        self,
        provider,
        addr,
        *,
        direction: str,
        baseline_nano: int,
        min_delta_nano: int,
        timeout: int = 75,
        interval: int = 7,
    ):
        """Ждёт реального изменения USDT-баланса после отправки свопа.

        direction="increase" — покупка (USDT должен прийти).
        direction="decrease" — продажа (USDT должен уйти).

        Возвращает текущий баланс (нано) при подтверждении или None, если за
        timeout сек изменение так и не наступило (своп отскочил / не исполнился).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(interval)
            try:
                cur = await self._usdt_balance_nano(provider, addr)
            except Exception as e:
                log.debug(f"[DeDust] settlement poll error: {e}")
                continue
            # Защита от ложного "своп подтверждён": если все три провайдера вернули 0,
            # но baseline > 0 — это API-сбой, а не реальное нулевание баланса.
            # Без этой проверки direction="decrease" давал True при любом API-отказе,
            # заставляя бот считать продажу исполненной когда она отскочила.
            if cur == 0 and baseline_nano > min_delta_nano:
                log.debug(
                    "[DeDust] settlement: cur=0 при baseline>0 — API-сбой, пропускаем итерацию"
                )
                continue
            if direction == "increase" and (cur - baseline_nano) >= min_delta_nano:
                return cur
            if direction == "decrease" and (baseline_nano - cur) >= min_delta_nano:
                return cur
        return None

    async def _wait_for_ton_increase(
        self,
        provider,
        addr,
        *,
        baseline_nano: int,
        min_delta_nano: int,
        timeout: int = 75,
        interval: int = 7,
    ):
        """Wait for the native-coin payout after a sell.

        A jetton balance decrease only proves that the transfer reached the
        pool.  It does not prove that the pool executed the swap.  Require a
        matching native-balance increase before returning ``ok=True``.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(interval)
            try:
                state = await provider.get_account_state(addr)
                cur = int(getattr(state, "balance", 0) or 0)
            except Exception as e:
                log.debug(f"[DeDust] TON settlement poll error: {e}")
                continue
            if cur - baseline_nano >= min_delta_nano:
                return cur
        return None

    def get_balance(self, force: bool = False) -> dict:
        """Надёжный баланс через глобальный кеш (не liteserver).

        Использует get_shared_balance() — единственный источник баланса для
        всего приложения. Исключает шторм 429 от параллельных читателей.
        force=True сбрасывает кеш (вызывается сразу после свопа).
        """
        return get_shared_balance(force=force)

    # ─────────────────────────── price / estimate ──────────────────────────

    def _usdt_address(self) -> Address:
        """Возвращает Address объект для USDT jetton master."""
        return Address(getattr(Config, "USDT_TOKEN_ADDRESS", Config.TOKEN_ADDRESS))

    async def _get_pool(self, provider):
        ton_asset = Asset.native()
        usdt_asset = Asset.jetton(self._usdt_address())
        # Реальный пул USDT/TON задан явным адресом (нестандартная комиссия 1%).
        # Factory.get_pool вернул бы канонический адрес дефолтной комиссии,
        # которого on-chain нет, и свопы отскакивали бы.
        pool_addr = (
            getattr(Config, "USDT_POOL_ADDRESS", "")
            or getattr(Config, "POOL_ADDRESS", "")
        ).strip()
        if pool_addr:
            pool = Pool.create_from_address(CoreAddress(pool_addr))
        else:
            pool = await Factory.get_pool(
                PoolType.VOLATILE, [ton_asset, usdt_asset], provider
            )
        return pool, ton_asset, usdt_asset

    async def _estimate_async(self, sell_asset, amount_nano: int) -> dict:
        provider = await self._make_provider()
        try:
            pool, ton_asset, usdt_asset = await self._get_pool(provider)
            result = await pool.get_estimated_swap_out(
                sell_asset, amount_nano, provider
            )
            return result
        finally:
            await provider.close_all()

    def get_price_ton_per_usdt(self) -> Optional[float]:
        """
        Цена 1 USDT в TON, рассчитанная из резервов пула.
        Кэшируется на 30 сек.
        """
        if not self._ready:
            return None
        try:

            async def _reserves():
                provider = await self._make_provider()
                try:
                    pool, _, _ = await self._get_pool(provider)
                    reserves = await pool.get_reserves(provider)
                    return reserves
                finally:
                    await provider.close_all()

            reserves = _run(_reserves())
            # reserves[0] = TON резерв (нано), reserves[1] = USDT резерв (base units)
            if reserves and reserves[0] > 0 and reserves[1] > 0:
                price = (reserves[0] / TON) / (reserves[1] / (10**Config.USDT_DECIMALS))
                self._last_price = price
                return price
        except Exception as e:
            log.debug(f"[DeDust] get_price ошибка: {e}")
        return self._last_price

    def estimate_buy(self, ton_amount: float) -> Optional[float]:
        """Сколько USDT получим за ton_amount TON (без исполнения)."""
        if not self._ready:
            return None
        try:
            nano = int(ton_amount * TON)
            result = _run(self._estimate_async(Asset.native(), nano))
            return result["amount_out"] / (10**Config.USDT_DECIMALS)
        except Exception as e:
            log.debug(f"[DeDust] estimate_buy ошибка: {e}")
            return None

    def estimate_sell(self, usdt_amount: float) -> Optional[float]:
        """Сколько TON получим за usdt_amount USDT (без исполнения)."""
        if not self._ready:
            return None
        try:
            nano = int(usdt_amount * (10**Config.USDT_DECIMALS))
            usdt_asset = Asset.jetton(self._usdt_address())
            result = _run(self._estimate_async(usdt_asset, nano))
            return result["amount_out"] / TON
        except Exception as e:
            log.debug(f"[DeDust] estimate_sell ошибка: {e}")
            return None

    # ─────────────────────── защита от проскальзывания ─────────────────────

    # Максимальная допустимая «протухлость» цены для исполнения свопа (сек).
    # USDT — 39-дневный мем-коин с ATR ~3-8%/свеча: 120 сек — слишком долго.
    # За 2 минуты цена может сдвинуться на 5-10%, что делает min-out неадекватным.
    # Снижено до 60 сек: прайс-фид обновляется каждые ~30 сек, запас ×2.
    _PRICE_MAX_STALE = 60

    # Максимальный допустимый ценовой импакт одной сделки на пул (% от резервов TON).
    # При $42K пуле: 100 TON = ~0.15% → ОК. При больших суммах — предупреждение.
    # Порог 3% = ~2000 TON (≈$1240): нереалистично для текущего баланса, но страхует.
    _MAX_POOL_IMPACT_PCT = 3.0

    @classmethod
    def _external_prices(cls) -> tuple:
        """Возвращает (ton_usd, usdt_usd) из внешнего прайс-фида или (None, None).

        Использует max_stale, чтобы не отдавать бесконечно устаревший кэш для
        исполнения свопа.
        """
        ton_usd = price_feed.get("TON", max_stale=cls._PRICE_MAX_STALE)
        usdt_usd = price_feed.get("USDT", max_stale=cls._PRICE_MAX_STALE)
        if ton_usd and usdt_usd and ton_usd > 0 and usdt_usd > 0:
            return ton_usd, usdt_usd
        return None, None

    # ── Реальные резервы пула (источник истины для курса свопа) ──────────────
    # Комиссия реального USDT/TON CPMM-пула: 10/10000 = 0.1%.
    # Значение подтверждено get_trade_fee на адресе пула.
    _POOL_FEE = 0.001
    _RESERVES_TIMEOUT = 8
    _RESERVES_CACHE_TTL = 120.0  # увеличен с 45→120с чтобы реже долбить API

    @staticmethod
    def _same_addr(a: str, b: str) -> bool:
        """Сравнивает TON-адреса независимо от формата (EQ/UQ/raw)."""
        try:
            return CoreAddress(a).to_str(is_user_friendly=False) == CoreAddress(
                b
            ).to_str(is_user_friendly=False)
        except Exception:
            return (a or "").lower() == (b or "").lower()

    def _pool_reserves(self):
        """Читает РЕАЛЬНЫЕ резервы пула (ton_reserve, usdt_reserve).

        Приоритет источников:
          1) TonCenter runGetMethod → get_reserves (резервы, которые использует CPMM)
          2) TonAPI account/jettons (fallback, ~3% off из-за gas/rent остатка)

        Возвращает (ton_reserve, usdt_reserve) в обычных единицах или None.
        Кэш: 120с. 429-backoff: 300с.
        """
        now = time.time()
        cached = getattr(self, "_pool_reserves_cache", None)
        cached_ts = getattr(self, "_pool_reserves_cache_ts", 0.0)
        if cached and (now - cached_ts) < self._RESERVES_CACHE_TTL:
            return cached

        # ── 429-backoff (только для TonAPI fallback) ─────────────────────────
        backoff_until = getattr(self, "_pool_reserves_backoff_until", 0.0)

        pool = Config.USDT_POOL_ADDRESS

        # ── 1. TonCenter runGetMethod: get_reserves (точные резервы CPMM) ──────
        try:
            r = _HTTP.post(
                "https://toncenter.com/api/v2/runGetMethod",
                headers={**_tc_headers(), "Content-Type": "application/json"},
                json={"address": pool, "method": "get_reserves", "stack": []},
                timeout=self._RESERVES_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                result = data.get("result", {}) if data.get("ok") else {}
                if result.get("exit_code") == 0:
                    stack = result.get("stack", [])
                    # DeDust CPMM get_reserves стек:
                    # [0] = TON reserve (nanoton)
                    # [1] = USDT reserve (base units, 6 decimals for USDT)
                    if len(stack) >= 2:

                        def _parse_stack_num(item):
                            # item: ["num","0x..."] или {"value":"0x..."}
                            raw = (
                                item[1]
                                if isinstance(item, list)
                                else item.get("value", "0")
                            )
                            s = str(raw)
                            if s.startswith("-0x"):
                                return -int(s[3:], 16)
                            if s.startswith("0x"):
                                return int(s, 16)
                            return int(s)

                        r0 = _parse_stack_num(stack[0])  # TON nanoton
                        r1 = _parse_stack_num(stack[1])  # USDT base units
                        ton_r = r0 / TON
                        usdt_r = r1 / (10**Config.USDT_DECIMALS)
                        if ton_r > 0 and usdt_r > 0:
                            reserves = (ton_r, usdt_r)
                            self._pool_reserves_cache = reserves
                            self._pool_reserves_cache_ts = now
                            self._pool_reserves_backoff_until = 0.0
                            return reserves
        except Exception as e:  # noqa: BLE001
            log.debug(f"[DeDust] get_pool_data TonCenter: {e}")

        # ── 2. TonAPI account/jettons (fallback) ──────────────────────────────
        if now < backoff_until:
            return cached  # TonAPI на паузе — вернуть последний удачный курс

        try:
            r1 = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{pool}",
                headers={"Accept": "application/json"},
                timeout=self._RESERVES_TIMEOUT,
            )
            if r1.status_code == 429:
                self._pool_reserves_backoff_until = now + 300.0  # пауза 5 минут
                log.warning("dedust_client: 429 от TonAPI (pool/balance) — пауза 300с")
                return cached
            r1.raise_for_status()
            r1_data = (
                r1.json()
                if r1.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            ton_reserve = (r1_data.get("balance", 0) or 0) / TON
            r2 = _HTTP.get(
                f"https://tonapi.io/v2/accounts/{pool}/jettons",
                headers={"Accept": "application/json"},
                timeout=self._RESERVES_TIMEOUT,
            )
            if r2.status_code == 429:
                self._pool_reserves_backoff_until = now + 300.0
                log.warning("dedust_client: 429 от TonAPI (pool/jettons) — пауза 300с")
                return cached
            r2.raise_for_status()
            r2_data = (
                r2.json()
                if r2.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            usdt_reserve = None
            for b in r2_data.get("balances", []):
                jetton = b.get("jetton", {}) or {}
                jaddr = jetton.get("address", "")
                jsymbol = (jetton.get("symbol", "") or "").upper()
                if self._same_addr(jaddr, Config.TOKEN_ADDRESS) or jsymbol == "USDT":
                    usdt_reserve = float(b.get("balance", 0)) / (
                        10**Config.USDT_DECIMALS
                    )
                    break
            if ton_reserve > 0 and usdt_reserve and usdt_reserve > 0:
                reserves = (ton_reserve, usdt_reserve)
                self._pool_reserves_cache = reserves
                self._pool_reserves_cache_ts = now
                self._pool_reserves_backoff_until = 0.0
                return reserves
        except Exception as e:  # noqa: BLE001
            log.warning(f"Не удалось прочитать резервы пула: {e}")

        return cached

    def _cpmm_out(
        self, amount_in: float, reserve_in: float, reserve_out: float
    ) -> float:
        """Точный выход свопа по формуле постоянного произведения (с комиссией 1%)."""
        amt = amount_in * (1 - self._POOL_FEE)
        return reserve_out * amt / (reserve_in + amt)

    def _min_out_buy_usdt(self, ton_amount: float):
        """Минимум USDT (нано), который должен прийти за ton_amount TON.

        Приоритет источников курса:
          1) РЕАЛЬНЫЕ резервы пула (точная CPMM-формула) — самый надёжный;
          2) priceNative пула (DexScreener) — серединная цена;
          3) перекрёстный USD-курс — последний резерв.
        Возвращает (min_nano, expected_usdt) или (None, None), если курс получить
        не удалось — тогда сделку нужно отклонить, а НЕ слать своп без защиты.
        """
        reserves = self._pool_reserves()
        if reserves:
            rt, rg = reserves
            # ── Pool impact guard (USDT/TON пул ~$42K) ─────────────────────
            # При низкой ликвидности большая покупка значимо двигает цену.
            # Предупреждаем, если наша сделка > _MAX_POOL_IMPACT_PCT% от пула TON.
            impact_pct = ton_amount / rt * 100.0 if rt > 0 else 0.0
            if impact_pct > self._MAX_POOL_IMPACT_PCT:
                log.warning(
                    f"[DeDust] ⚠️ Высокий pool impact: {ton_amount:.1f} TON = "
                    f"{impact_pct:.1f}% от резерва пула ({rt:.0f} TON). "
                    f"Slippage может превысить {Config.SLIPPAGE_PCT:.0f}%."
                )
            expected_usdt = self._cpmm_out(ton_amount, rt, rg)
        else:
            ton_per_usdt = price_feed.get_usdt_ton_price(
                max_stale=self._PRICE_MAX_STALE
            )
            if ton_per_usdt and ton_per_usdt > 0:
                expected_usdt = ton_amount / ton_per_usdt
            else:
                ton_usd, usdt_usd = self._external_prices()
                if ton_usd is None:
                    return None, None
                expected_usdt = (ton_amount * ton_usd) / usdt_usd
        min_usdt = expected_usdt * (1 - Config.SLIPPAGE_PCT / 100.0)
        return int(min_usdt * (10**Config.USDT_DECIMALS)), expected_usdt

    def _min_out_sell_ton(self, usdt_amount: float):
        """Минимум TON (нано), который должен прийти за usdt_amount USDT.

        Источники курса в том же приоритете, что и для покупки.
        Возвращает (min_nano, expected_ton) или (None, None), если цены нет.
        """
        reserves = self._pool_reserves()
        if reserves:
            rt, rg = reserves
            expected_ton = self._cpmm_out(usdt_amount, rg, rt)
        else:
            ton_per_usdt = price_feed.get_usdt_ton_price(
                max_stale=self._PRICE_MAX_STALE
            )
            if ton_per_usdt and ton_per_usdt > 0:
                expected_ton = usdt_amount * ton_per_usdt
            else:
                ton_usd, usdt_usd = self._external_prices()
                if ton_usd is None:
                    return None, None
                expected_ton = (usdt_amount * usdt_usd) / ton_usd
        min_ton = expected_ton * (1 - Config.SLIPPAGE_PCT / 100.0)
        return int(min_ton * TON), expected_ton

    # ─────────────── построение тела свопа ───────────────────────────────────
    # This TON/USDT pool is a legacy DeDust Vault pool, not a CPMM-v2 pool.
    # CPMM-v2 PayJetton (0xcbc33949) is accepted by the jetton wallet but
    # aborts inside this pool with exit code 65535, leaving the input assets
    # in the pool.  Use the legacy VaultJetton/DedustSwap payload instead.
    _JETTON_XFER_OP = 0x0F8A7EA5  # стандартный jetton transfer

    def _build_sell_transfer_body(
        self,
        recipient,
        pool_addr,
        usdt_nano: int,
        min_out_nano: int,
        deadline: int,
        fwd_nano: int,
    ):
        """Build a TEP-74 transfer with the legacy DeDust swap payload."""
        forward_payload = VaultJetton.create_swap_payload(
            pool_address=pool_addr,
            limit=min_out_nano,
            swap_params=SwapParams(
                deadline=deadline,
                recipient_address=recipient,
            ),
        )
        return (
            begin_cell()
            .store_uint(self._JETTON_XFER_OP, 32)
            .store_uint(secrets.randbits(64), 64)
            .store_coins(usdt_nano)
            .store_address(pool_addr)  # destination = ПУЛ
            .store_address(recipient)  # response_destination
            .store_maybe_ref(None)  # custom_payload = нет
            .store_coins(fwd_nano)  # forward_ton_amount
            .store_bit(1)  # forward_payload в ref
            .store_ref(forward_payload)
            .end_cell()
        )

    # ─────────────────────────── swap: buy ─────────────────────────────────

    async def _buy_async(self, ton_amount: float) -> dict:
        """TON → USDT: отправляем swap-payload в DeDust Native Vault."""
        # Защита от проскальзывания: считаем min-out ДО отправки средств.
        min_out_nano, expected_usdt = self._min_out_buy_usdt(ton_amount)
        if min_out_nano is None:
            return {
                "ok": False,
                "side": "buy",
                "error": (
                    "Нет актуальной цены USDT/TON для расчёта защиты от "
                    "проскальзывания — сделка отклонена (своп без min-out не "
                    "отправляется во избежание убыточного курса)."
                ),
            }

        wallet, provider = await self._wallet_and_provider()
        try:
            pool, ton_asset, _ = await self._get_pool(provider)
            native_vault = await Factory.get_native_vault(provider)

            amount_nano = int(ton_amount * TON)
            # Native Vault принимает swap-payload и сам маршрутизирует TON в пул.
            # Для этого пула рабочая on-chain транзакция прикладывала 0.25 TON
            # сверх суммы swap (0.45 TON total для покупки 0.2 TON).
            gas_nano = max(int(Config.BUY_GAS_TON * TON), int(0.25 * TON))

            # ── Preflight: деплой кошелька если uninit ───────────────────────
            # WalletV5R1 может быть uninit если на адрес уже пришли TON,
            # но первый исходящий tx (deploy) ещё не был отправлен.
            # В этом случае get_seqno() падает с exit_code=-256.
            if not await self._ensure_wallet_deployed(wallet, provider):
                return {
                    "ok": False,
                    "side": "buy",
                    "error": (
                        "Кошелёк не инициализирован на блокчейне — "
                        "автодеплой не удался. Отправьте 0.05 TON самому себе "
                        "из TonKeeper/mytonwallet чтобы активировать кошелёк."
                    ),
                }

            # ── Preflight: хватает ли TON на сумму свопа + газ? ──────────────
            # Покупка отправляет amount_nano (на своп) + gas_nano (газ/комиссии).
            # Если на кошельке меньше — НЕ отправляем операцию вовсе, чтобы не
            # сжечь газ на заведомо неисполнимой транзакции.
            state = await provider.get_account_state(wallet.address)
            ton_nano = getattr(state, "balance", 0) or 0
            needed_nano = (
                amount_nano + gas_nano + int(0.05 * TON)
            )  # +запас на комиссии сети
            if ton_nano < needed_nano:
                return {
                    "ok": False,
                    "side": "buy",
                    "error": (
                        f"Недостаточно TON на кошельке платформы: есть "
                        f"{ton_nano / TON:.3f} TON, нужно ≥ {needed_nano / TON:.2f} TON "
                        f"(своп {ton_amount:.3f} + газ). Покупка отклонена."
                    ),
                    "need_ton": round(needed_nano / TON, 2),
                    "have_ton": round(ton_nano / TON, 3),
                }

            deadline = int(time.time()) + 600
            body = VaultNative.create_swap_payload(
                amount=amount_nano,
                pool_address=pool.address,
                limit=min_out_nano,
                swap_params=SwapParams(deadline=deadline),
            )

            # Базовый USDT-баланс ДО свопа — для проверки реального исполнения.
            baseline_nano = await self._usdt_balance_nano(provider, wallet.address)

            await wallet.transfer(
                destination=native_vault.address,
                amount=amount_nano + gas_nano,
                body=body,
            )

            # ── Проверка реального исполнения on-chain ───────────────────────
            # wallet.transfer лишь ШИРОКОВЕЩАЕТ транзакцию; своп в пуле может
            # отскочить (bounce) уже после отправки. Поэтому ждём, пока USDT
            # реально поступит. Требуем хотя бы половину ожидаемого объёма.
            min_delta = int(expected_usdt * 0.5 * (10**Config.USDT_DECIMALS))
            confirmed = await self._wait_for_settlement(
                provider,
                wallet.address,
                direction="increase",
                baseline_nano=baseline_nano,
                min_delta_nano=min_delta,
            )
            if confirmed is None:
                return {
                    "ok": False,
                    "side": "buy",
                    "broadcast": True,
                    "error": (
                        "Своп отправлен, но USDT не поступил — ордер отскочил "
                        "(bounce) в пуле DeDust. TON возвращён на кошелёк (минус "
                        "сетевой газ). Вероятные причины: проскальзывание выше "
                        f"{Config.SLIPPAGE_PCT}% или нехватка ликвидности."
                    ),
                }

            return {
                "ok": True,
                "side": "buy",
                "ton_spent": ton_amount,
                "pool": str(pool.address),
                "min_usdt_out": round(min_out_nano / (10**Config.USDT_DECIMALS), 6),
                "expected_usdt": round(expected_usdt, 6),
                "usdt_received": round(
                    (confirmed - baseline_nano) / (10**Config.USDT_DECIMALS), 6
                ),
                "slippage_pct": Config.SLIPPAGE_PCT,
            }
        finally:
            await provider.close_all()

    def buy(self, ton_amount: float) -> dict:
        """Покупка USDT за TON через DeDust. Блокирует до завершения транзакции."""
        if not self._ready:
            return {"ok": False, "error": self._error}
        # Сериализуем свопы на общем кастодиальном кошельке: проверка исполнения
        # опирается на изменение USDT-баланса, поэтому параллельные buy/sell
        # могли бы дать ложный результат. Лок гарантирует один своп за раз.
        with self._lock:
            try:
                result = _run(self._buy_async(ton_amount))
            except Exception as e:
                log.error(f"[DeDust] buy ошибка: {e}")
                return {"ok": False, "error": str(e)}
        if result.get("ok"):
            # Баланс изменился on-chain — форсируем обновление общего кеша,
            # иначе последующая сделка может сайзиться по устаревшим данным
            # (до 150с TTL).
            try:
                get_shared_balance(force=True)
            except Exception:
                pass
        return result

    # ─────────────────────────── swap: sell ────────────────────────────────

    async def _sell_async(self, usdt_amount: float, min_net_ton: float = None) -> dict:
        """USDT → TON: jetton-transfer USDT НАПРЯМУЮ в пул с forward-payload свопа.

        Газ: 0.35 TON прикладывается к сообщению; 0.25 TON форвардится в пул на
        исполнение свопа. Излишек возвращается на кошелёк.

        min_net_ton — минимум TON нетто (после газа), который должна вернуть продажа.
        Если ожидаемый выход ниже — своп блокируется ДО отправки транзакции в сеть.
        """
        # Защита от проскальзывания: считаем min-out TON ДО перевода жеттонов.
        min_out_nano, expected_ton = self._min_out_sell_ton(usdt_amount)
        if min_out_nano is None:
            return {
                "ok": False,
                "side": "sell",
                "error": (
                    "Нет актуальной цены USDT/TON для расчёта защиты от "
                    "проскальзывания — продажа отклонена (своп без min-out не "
                    "отправляется во избежание убыточного курса)."
                ),
            }

        # ── AMM preflight: проверка прибыльности по реальному выходу свопа ──────
        # expected_ton — то что придёт из пула (CPMM с учётом price impact).
        # Вычитаем реальный net-gas продажи (подтверждён on-chain: ~0.253 TON).
        # Если нетто < min_net_ton — блокируем ДО отправки транзакции в блокчейн.
        if min_net_ton is not None and min_net_ton > 0:
            sell_gas = Config.SELL_GAS_TON
            net_received = expected_ton - sell_gas
            if net_received < min_net_ton:
                shortfall = min_net_ton - net_received
                log.warning(
                    f"[DeDust] 🛡️ AMM preflight BLOCKED: ожидаем {net_received:.4f} TON нетто "
                    f"(из пула {expected_ton:.4f} − газ {sell_gas:.3f}), "
                    f"нужно ≥ {min_net_ton:.4f} TON. Дефицит {shortfall:.4f} TON."
                )
                return {
                    "ok": False,
                    "side": "sell",
                    "amm_blocked": True,
                    "error": (
                        f"🛡️ AMM preflight: продажа заблокирована — "
                        f"пул вернёт {expected_ton:.3f} TON (price impact учтён), "
                        f"за вычетом газа {sell_gas:.3f} = {net_received:.3f} TON нетто. "
                        f"Нужно ≥ {min_net_ton:.3f} TON чтобы выйти без убытка. "
                        f"Дефицит: {shortfall:.3f} TON. "
                        f"Транзакция НЕ отправлена в сеть."
                    ),
                    "expected_ton": round(expected_ton, 4),
                    "net_ton": round(net_received, 4),
                    "min_net_ton": round(min_net_ton, 4),
                    "shortfall_ton": round(shortfall, 4),
                }
            else:
                surplus = net_received - min_net_ton
                log.info(
                    f"[DeDust] ✅ AMM preflight OK: ожидаем {net_received:.4f} TON нетто "
                    f"(нужно ≥ {min_net_ton:.4f}, запас +{surplus:.4f} TON)"
                )

        wallet, provider = await self._wallet_and_provider()
        try:
            pool, _, usdt_asset = await self._get_pool(provider)

            # ── Газ для sell ────────────────────────────────────────────────
            # This matches a known successful legacy DeDust trace for this
            # pool: 0.25 TON to the jetton wallet and 0.18 TON forwarded to
            # the pool.  The unused remainder is returned as excesses.
            gas_nano = int(0.30 * TON)
            fwd_nano = int(0.25 * TON)

            # ── Preflight: деплой кошелька если uninit ───────────────────────
            if not await self._ensure_wallet_deployed(wallet, provider):
                return {
                    "ok": False,
                    "side": "sell",
                    "error": (
                        "Кошелёк не инициализирован на блокчейне — "
                        "автодеплой не удался. Отправьте 0.05 TON самому себе "
                        "из TonKeeper/mytonwallet чтобы активировать кошелёк."
                    ),
                }

            # ── Preflight: хватает ли TON на газ? ──────────────────────────
            state = await provider.get_account_state(wallet.address)
            ton_nano = getattr(state, "balance", 0) or 0
            baseline_ton_nano = int(ton_nano)
            # L4-fix: gas_nano уже включает все расходы; extra 0.01 TON создавал
            # ложную блокировку при пограничном балансе → убираем двойной счёт.
            needed_nano = gas_nano
            if ton_nano < needed_nano:
                return {
                    "ok": False,
                    "side": "sell",
                    "error": (
                        f"Недостаточно TON для газа: на кошельке "
                        f"{ton_nano / TON:.3f} TON, нужно ≥ {needed_nano / TON:.2f} TON. "
                        f"Пополните кошелёк TON, чтобы продать USDT."
                    ),
                    "need_ton": round(needed_nano / TON, 2),
                    "have_ton": round(ton_nano / TON, 3),
                }

            # ── Адрес USDT jetton-кошелька ────────────────────────────────
            # TonCenter v3 → TonAPI; SDK намеренно последний резерв.
            owner_addr_str = self._clean_addr_str(wallet.address)
            jw_addr_str = self._usdt_jetton_wallet_addr_via_api(owner_addr_str)
            if jw_addr_str:
                from pytoniq_core import Address as _CoreAddr

                usdt_jw_address = _CoreAddr(jw_addr_str)
                log.info(f"[DeDust] USDT jetton wallet: {jw_addr_str}")
            else:
                # H1: Оба API не ответили → прерываем продажу (SDK fallback даёт неверный
                # адрес для USDT и мог привести к безвозвратной потере токенов).
                log.error(
                    "[DeDust] SELL ABORTED: не удалось получить адрес USDT jetton-кошелька "
                    "ни через TonCenter, ни через TonAPI. Продажа отменена для защиты токенов."
                )
                return {
                    "ok": False,
                    "side": "sell",
                    "error": (
                        "Не удалось получить адрес USDT jetton-кошелька (TonCenter и TonAPI недоступны). "
                        "Продажа отменена — USDT в безопасности. Повторите позже."
                    ),
                }

            # ── Точный USDT-баланс on-chain ДО свопа ──────────────────────
            # КРИТИЧНО: используем on-chain нано-баланс, а НЕ float usdt_amount!
            # int(float * 1e9) может дать значение ВЫШЕ реального баланса из-за
            # потери точности, и jetton-кошелёк отвергнет transfer с exit_code=27.
            baseline_nano = await self._usdt_balance_nano(provider, wallet.address)

            # Сумма продажи: либо запрошенная сумма, либо весь баланс — берём MIN
            # чтобы избежать превышения баланса из-за float-округления.
            amount_nano = min(
                int(usdt_amount * (10**Config.USDT_DECIMALS)), baseline_nano
            )
            if amount_nano <= 0:
                return {
                    "ok": False,
                    "side": "sell",
                    "error": "USDT-баланс на кошельке равен 0 (нечего продавать).",
                }
            log.info(
                f"[DeDust] SELL {amount_nano/(10 ** Config.USDT_DECIMALS):.6f} USDT (requested={usdt_amount:.6f}, on-chain={baseline_nano/(10 ** Config.USDT_DECIMALS):.6f})"
            )

            deadline = int(time.time()) + 600  # 10 мин
            transfer_body = self._build_sell_transfer_body(
                recipient=wallet.address,
                pool_addr=pool.address,
                usdt_nano=amount_nano,
                min_out_nano=min_out_nano,
                deadline=deadline,
                fwd_nano=fwd_nano,
            )

            # USDT уходит jetton-transfer'ом В ПУЛ (destination=пул); своп
            # исполняется внутри пула по forward-payload. Сообщение шлём на наш
            # USDT jetton-кошелёк, он маршрутизирует жетоны в пул.
            await wallet.transfer(
                destination=usdt_jw_address,
                amount=gas_nano,
                body=transfer_body,
            )

            # ── Проверка реального исполнения on-chain ───────────────────────
            # Если своп отскочит, USDT вернётся на кошелёк и баланс НЕ
            # уменьшится. Ждём фактического списания (хотя бы половины объёма).
            min_delta = int(amount_nano * 0.5)
            confirmed = await self._wait_for_settlement(
                provider,
                wallet.address,
                direction="decrease",
                baseline_nano=baseline_nano,
                min_delta_nano=min_delta,
            )
            if confirmed is None:
                return {
                    "ok": False,
                    "side": "sell",
                    "broadcast": True,
                    "error": (
                        "Своп отправлен, но USDT не списался — ордер отскочил "
                        "(bounce) в пуле DeDust. USDT возвращён на кошелёк "
                        "(минус сетевой газ). Вероятные причины: проскальзывание "
                        f"выше {Config.SLIPPAGE_PCT}% или нехватка ликвидности."
                    ),
                }

            # Do not report success merely because USDT left the wallet:
            # the previous CPMM-v2 payload did exactly that and then aborted
            # inside the pool.  Allow a small fee buffer below min-out.
            fee_buffer_nano = int(0.02 * TON)
            min_ton_delta = max(min_out_nano - fee_buffer_nano, 1)
            ton_confirmed = await self._wait_for_ton_increase(
                provider,
                wallet.address,
                baseline_nano=baseline_ton_nano,
                min_delta_nano=min_ton_delta,
            )
            if ton_confirmed is None:
                return {
                    "ok": False,
                    "side": "sell",
                    "broadcast": True,
                    "settlement_unverified": True,
                    "usdt_sold": round(
                        (baseline_nano - confirmed)
                        / (10**Config.USDT_DECIMALS),
                        6,
                    ),
                    "error": (
                        "USDT списался, но ожидаемый приход GRAM не подтверждён "
                        "on-chain. Повторная продажа автоматически не выполняется."
                    ),
                }

            return {
                "ok": True,
                "side": "sell",
                "usdt_spent": usdt_amount,
                "pool": str(pool.address),
                "min_ton_out": round(min_out_nano / TON, 6),
                "expected_ton": round(expected_ton, 6),
                "usdt_sold": round(
                    (baseline_nano - confirmed) / (10**Config.USDT_DECIMALS), 6
                ),
                "ton_received": round(
                    (ton_confirmed - baseline_ton_nano) / TON, 6
                ),
                "slippage_pct": Config.SLIPPAGE_PCT,
            }
        finally:
            await provider.close_all()

    def sell(self, usdt_amount: float, min_net_ton: float = None) -> dict:
        """Продажа USDT за TON через DeDust. Блокирует до завершения транзакции.

        min_net_ton — минимум TON нетто (после газа) для разрешения продажи.
        Если AMM вернёт меньше — транзакция НЕ отправляется, возвращается ошибка
        с amm_blocked=True и деталями (expected_ton, net_ton, shortfall_ton).
        """
        if not self._ready:
            return {"ok": False, "error": self._error}
        # Сериализуем свопы (см. комментарий в buy): один своп за раз, иначе
        # параллельные операции исказят проверку USDT-баланса.
        with self._lock:
            try:
                result = _run(self._sell_async(usdt_amount, min_net_ton=min_net_ton))
            except Exception as e:
                log.error(f"[DeDust] sell ошибка: {e}")
                return {"ok": False, "error": str(e)}
        if result.get("ok"):
            try:
                get_shared_balance(force=True)
            except Exception:
                pass
        return result

    # ─────────────────────────── transfer TON ──────────────────────────────

    async def _send_ton_async(self, recipient: str, amount_ton: float) -> dict:
        """Отправка TON на указанный адрес (для сбора комиссии платформы)."""
        wallet, provider = await self._wallet_and_provider()
        try:
            dest = Address(recipient)
            await wallet.transfer(
                destination=dest,
                amount=int(amount_ton * TON),
            )
            return {"ok": True, "amount": amount_ton, "to": recipient}
        finally:
            await provider.close_all()

    def send_ton(self, recipient: str, amount_ton: float) -> dict:
        """Отправляет amount_ton TON на адрес recipient (комиссия платформы).

        Выполняется под тем же _lock, что buy/sell — чтобы исключить конфликт
        seqno при параллельном вызове вывода и свопа на одном кошельке.
        """
        if not self._ready:
            return {"ok": False, "error": self._error}
        if amount_ton <= 0:
            return {"ok": False, "error": "amount <= 0"}
        with self._lock:
            try:
                return _run(self._send_ton_async(recipient, amount_ton))
            except Exception as e:
                log.error(f"[DeDust] send_ton ошибка: {e}")
                return {"ok": False, "error": str(e)}

    def get_wallet_address(self) -> Optional[str]:
        """Возвращает адрес кошелька (EQ-формат) без подключения к сети."""
        if not self._ready:
            return None
        try:

            async def _addr():
                provider = await self._make_provider()
                try:
                    wallet = await WalletV5R1.from_mnemonic(
                        provider=provider,
                        mnemonics=self._mnemonic,
                        network_global_id=-239,
                    )
                    return wallet.address.to_str(
                        is_user_friendly=True, is_bounceable=True
                    )
                finally:
                    await provider.close_all()

            return _run(_addr())
        except Exception as e:
            log.debug(f"[DeDust] get_wallet_address ошибка: {e}")
            return None


# Синглтон — создаётся один раз при импорте
dedust_client = DedustClient()
