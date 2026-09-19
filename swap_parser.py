#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
swap_parser.py — парсер свапов и возвратов газа по трассе TON (TonAPI v2).

Источники данных (без хардкода символов/decimals):
  GET /v2/events/{id}    -> декодированные действия (JettonSwap), value_flow
  GET /v2/traces/{hash}  -> полное дерево транзакций (газ, refund'ы, bound-gas)
  GET /v2/jettons/{addr} -> метаданные jetton (symbol, decimals)

CLI:
  python3 swap_parser.py <hash|event_id>              # один свап
  python3 swap_parser.py <hash> --json                # машинный JSON
  python3 swap_parser.py --fixture-dir /tmp           # оффлайн: /tmp/tr.json + /tmp/ev.json
  python3 swap_parser.py --watch <wallet> --limit 20  # последние свапы кошелька (для бота)
  python3 swap_parser.py <hash> --store --db swaps.db        # разобрать и сохранить в SQLite
  python3 swap_parser.py --watch <w> --store --db swaps.db   # массовая запись свапов кошелька
  python3 swap_parser.py --history --limit 50 --db swaps.db  # история свапов (таблица)
  python3 swap_parser.py --pnl --db swaps.db                 # PnL-отчёт по портфелю
  python3 swap_parser.py --density --db swaps.db             # плотность свапов (по времени/часам/DEX)
  python3 swap_parser.py --density --bucket day --db swaps.db # плотность по дням

Модуль:
  from swap_parser import parse_swap, format_bot_message
  print(format_bot_message(parse_swap("3d956a...")))
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

TONAPI = "https://tonapi.io/v2"
TON_DECIMALS = 9
EXCESSES_OPS = {"0xd53276db", "0x7bdd97de"}  # excesses / refund газа


# ---------------------------------------------------------------- fetch layer
def _get(url: str, tries: int = 4, timeout: int = 30):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "swap-parser/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # 429/5xx -> backoff
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"TonAPI fail {url}: {last}")


class TonAPI:
    def __init__(self):
        self._jettons: dict[str, dict] = {}

    def event(self, event_id: str) -> dict:
        return _get(f"{TONAPI}/events/{event_id}")

    def trace(self, tx_hash: str) -> dict:
        return _get(f"{TONAPI}/traces/{tx_hash}")

    def jetton(self, addr: str) -> dict:
        if addr and addr not in self._jettons:
            try:
                self._jettons[addr] = _get(f"{TONAPI}/jettons/{addr}")
            except Exception:
                self._jettons[addr] = {}
        return self._jettons.get(addr, {})

    def account_events(self, wallet: str, limit: int = 20) -> list[dict]:
        d = _get(f"{TONAPI}/accounts/{wallet}/events?limit={limit}")
        return d if isinstance(d, list) else (d.get("events") or [])

    def chart(
        self, token: str, currency: str = "usd", start: int = 0, end: int = 0
    ) -> dict:
        return _get(
            f"{TONAPI}/rates/chart?token={token}&currency={currency}"
            f"&start_date={start}&end_date={end}"
        )

    def rate(self, token: str, currency: str = "usd") -> dict:
        return _get(f"{TONAPI}/rates?tokens={token}&currencies={currency}")


# ---------------------------------------------------------------- helpers
def _a(x):
    return x.get("address") if isinstance(x, dict) else x


def _n(x):
    return x.get("name") if isinstance(x, dict) else None


def _dec(m):
    return (m or {}).get("decoded_body") or (m or {}).get("decoded_op")


def iter_txs(node: dict):
    """Разворачивает любой узел трассы ({'transaction':..,'children':[..]} или сам tx)."""
    tx = (
        node.get("transaction")
        if isinstance(node, dict) and "transaction" in node
        else node
    )
    if isinstance(tx, dict) and "hash" in tx:
        yield tx
    for c in (node.get("children") or []) if isinstance(node, dict) else []:
        yield from iter_txs(c)


def norm_addr(a: str) -> str:
    return (a or "").lower()


@dataclass
class Meta:
    symbol: str = "TON"
    name: str = "Toncoin"
    decimals: int = TON_DECIMALS
    address: str = "native"
    usd: float | None = None

    def scale(self, raw) -> float:
        return int(raw or 0) / (10**self.decimals)


@dataclass
class Leg:
    dex: str
    token_in: Meta
    token_out: Meta
    amount_in_raw: int
    amount_out_raw: int
    amount_in: float
    amount_out: float
    usd_in: float | None = None
    usd_out: float | None = None


@dataclass
class Refund:
    op: str
    amount_raw: int
    amount: float
    to: str
    kind: str


@dataclass
class SwapAnalysis:
    tx_hash: str = ""
    event_id: str = ""
    timestamp: int = 0
    wallet: str = ""
    dex: str = ""
    token_in: Meta | None = None
    token_out: Meta | None = None
    amount_in: float = 0.0
    amount_out: float = 0.0
    rate: float | None = None
    rate_inverse: float | None = None
    legs: list = field(default_factory=list)
    hops: int = 0
    gas_bound: float = 0.0
    gas_refunded: float = 0.0
    gas_spent: float = 0.0
    net_ton_change: float = 0.0
    net_jetton_change: dict = field(default_factory=dict)
    total_fees: float = 0.0
    tx_count: int = 0
    refunds: list = field(default_factory=list)
    success: bool = True
    is_scam: bool = False
    # ---- USD-оценка (исторический курс на момент свапа, не текущий)
    usd_in: float | None = None
    usd_out: float | None = None
    usd_net: float | None = None
    usd_rate: float | None = None
    usd_gas_bound: float | None = None
    usd_gas_refunded: float | None = None
    usd_gas_spent: float | None = None
    usd_total_fees: float | None = None
    price_source: str = ""
    price_errors: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        return d


# ---------------------------------------------------------------- цены (USD)
@dataclass
class Price:
    usd: float | None = None
    source: str = ""
    ts: int = 0
    error: str | None = None


class PriceOracle:
    """Исторический USD-курс на utime транзакции.
    Основной источник : TonAPI /v2/rates/chart → ближайшая точка к ts.
    Фолбэк           : TonAPI /v2/rates (текущий курс) — помечается в source/ts.
    Если ни один источник не дал цену → usd=None + причина в error (без выдумок)."""

    def __init__(self, api: "TonAPI", window: int = 172800, max_skew: int = 7200):
        self.api = api
        self.window = window
        self.max_skew = max_skew
        self._cache: dict[tuple, Price] = {}

    @staticmethod
    def key(addr: str, symbol: str) -> str:
        if (addr or "").lower() in ("", "native") or (symbol or "").upper() == "TON":
            return "ton"
        return addr

    def at(self, addr: str, symbol: str, ts: int) -> Price:
        k = self.key(addr, symbol)
        ck = (k, ts // 3600)
        if ck in self._cache:
            return self._cache[ck]
        p = Price()
        if ts:
            try:
                pts = (
                    self.api.chart(k, "usd", ts - self.window, ts + self.window) or {}
                ).get("points") or []
                if pts:
                    best = min(pts, key=lambda x: abs(int(x[0]) - ts))
                    skew = abs(int(best[0]) - ts)
                    if skew <= self.max_skew:
                        p = Price(
                            usd=float(best[1]),
                            source="tonapi/rates/chart",
                            ts=int(best[0]),
                        )
                    else:
                        p.error = f"chart: ближайшая точка дальше {self.max_skew}s"
                else:
                    p.error = "chart: нет точек"
            except Exception as e:
                p.error = f"chart: {e}"
        if p.usd is None:
            try:
                rt = (self.api.rate(k, "usd") or {}).get("rates") or {}
                r = (
                    rt.get(k)
                    or rt.get(k.upper())
                    or (next(iter(rt.values())) if rt else None)
                )
                if r and (r.get("prices") or {}).get("USD") is not None:
                    p = Price(
                        usd=float(r["prices"]["USD"]),
                        source="tonapi/rates(текущий)",
                        ts=0,
                    )
                else:
                    p.error = (p.error + "; " if p.error else "") + "rates: нет курса"
            except Exception as e:
                p.error = (p.error + "; " if p.error else "") + f"rates: {e}"
        self._cache[ck] = p
        return p


# ---------------------------------------------------------------- normalizer
def _meta_for(api: TonAPI, master: dict | None) -> Meta:
    if not master:
        return Meta()
    addr = _a(master) or master.get("address") or ""
    j = api.jetton(addr)
    md = j.get("metadata", {}) if isinstance(j, dict) else {}
    return Meta(
        symbol=master.get("symbol") or md.get("symbol") or (addr[:6] if addr else "?"),
        name=master.get("name") or md.get("name") or "",
        decimals=int(
            master.get("decimals")
            if master.get("decimals") is not None
            else (j.get("decimals") if j.get("decimals") is not None else TON_DECIMALS)
        ),
        address=addr or "native",
    )


def normalize(ev: dict, tr: dict, api: TonAPI) -> SwapAnalysis:
    a = SwapAnalysis()
    a.event_id = ev.get("event_id", "")
    a.timestamp = int(ev.get("timestamp") or 0)
    a.is_scam = bool(ev.get("is_scam"))

    swaps = [
        act for act in (ev.get("actions") or []) if act.get("type") == "JettonSwap"
    ]
    if not swaps:
        raise ValueError("в событии нет действий JettonSwap")

    legs = []
    for act in swaps:
        j = act.get("JettonSwap") or {}
        ok = act.get("status") == "ok"
        a.success = a.success and ok
        dex = j.get("dex") or "?"
        tin = _meta_for(api, j.get("jetton_master_in"))
        tout = _meta_for(api, j.get("jetton_master_out"))
        # TON-лег: ton_out / ton_in присутствуют, когда сторона — нативный TON
        if not j.get("jetton_master_out") and (j.get("ton_out") or 0) > 0:
            tout = Meta(symbol="TON", name="Toncoin", decimals=TON_DECIMALS)
        if not j.get("jetton_master_in") and (j.get("ton_in") or 0) > 0:
            tin = Meta(symbol="TON", name="Toncoin", decimals=TON_DECIMALS)
        ain_raw = int(
            (j.get("ton_in") if tin.symbol == "TON" else j.get("amount_in")) or 0
        )
        aout_raw = int(
            (j.get("ton_out") if tout.symbol == "TON" else j.get("amount_out")) or 0
        )
        legs.append(
            Leg(
                dex=dex,
                token_in=tin,
                token_out=tout,
                amount_in_raw=ain_raw,
                amount_out_raw=aout_raw,
                amount_in=tin.scale(ain_raw),
                amount_out=tout.scale(aout_raw),
            )
        )
        if not a.wallet:
            a.wallet = _a(j.get("user_wallet")) or ""

    a.legs = legs
    a.hops = len(legs)
    a.dex = legs[0].dex
    # мультихоп -> сворачиваем в нетто in/out
    a.token_in, a.token_out = legs[0].token_in, legs[-1].token_out
    a.amount_in = legs[0].amount_in
    a.amount_out = legs[-1].amount_out
    if a.amount_in and a.amount_out:
        a.rate = a.amount_out / a.amount_in
        a.rate_inverse = a.amount_in / a.amount_out

    # ---- газ и refund'ы из дерева трассы
    root = {
        "transaction": tr.get("transaction", {}),
        "children": tr.get("children") or [],
    }
    txs = list(iter_txs(root))
    a.tx_count = len(txs)
    a.total_fees = sum(int(t.get("total_fees") or 0) for t in txs) / 1e9
    wallet = norm_addr(a.wallet)
    refunds = []
    # Входящие TON на кошелёк приходят КАК in_msg дочерних транзакций,
    # чей account == кошелёк (а не как out_msg чужой транзакции).
    incoming = 0
    for t in txs:
        if norm_addr(_a(t.get("account"))) != wallet:
            continue
        m = t.get("in_msg") or {}
        if (m.get("msg_type") or "") == "ext_in_msg":
            continue
        if norm_addr(_a(m.get("source"))) == wallet:
            continue
        v = int(m.get("value") or 0)
        if v <= 0:
            continue
        op = (m.get("op_code") or "").lower()
        incoming += v
        if op in EXCESSES_OPS:
            refunds.append(
                Refund(
                    op=op,
                    amount_raw=v,
                    amount=v / 1e9,
                    to=wallet,
                    kind="excesses (возврат газа)",
                )
            )
    # резерв: внешние out_msg на кошелёк (некоторые роутеры)
    for t in txs:
        if norm_addr(_a(t.get("account"))) == wallet:
            continue
        for m in t.get("out_msgs") or []:
            if norm_addr(_a(m.get("destination"))) != wallet:
                continue
            v = int(m.get("value") or 0)
            op = (m.get("op_code") or "").lower()
            incoming += v
            if op in EXCESSES_OPS:
                refunds.append(
                    Refund(
                        op=op,
                        amount_raw=v,
                        amount=v / 1e9,
                        to=wallet,
                        kind="excesses (возврат газа)",
                    )
                )
    # bound-gas = TON, привязанный к forward-сообщению jetton_transfer (только jetton-in свапы).
    # Для TON-in свапов привязанного газа нет — иначе в gas_bound попадала бы сумма самого свапа.
    JETTON_TRANSFER_OPS = {"0x0f8a7ea5", "0xf8a7ea5"}
    if len(txs) > 1:
        m1 = txs[1].get("in_msg") or {}
        if (m1.get("op_code") or "").lower() in JETTON_TRANSFER_OPS:
            v = int(m1.get("value") or 0) / 1e9
            if 0 < v <= 5.0:  # защитный предел разумного привязанного газа
                a.gas_bound = v
    # выплата в TON = валидный выход свапа; всё сверх — возврат газа
    payout = a.amount_out if a.token_out and a.token_out.symbol == "TON" else 0.0
    a.gas_refunded = max(0.0, incoming / 1e9 - payout)
    a.gas_spent = max(0.0, a.gas_bound - a.gas_refunded)
    if a.gas_refunded > 0:
        extra = a.gas_refunded - sum(r.amount for r in refunds)
        if extra > 1e-9:
            refunds.append(
                Refund(
                    op="0x474f86cf",
                    amount_raw=int(extra * 1e9),
                    amount=extra,
                    to=wallet,
                    kind="остаток forward-газа вместе с выплатой",
                )
            )
    a.refunds = refunds

    # ---- USD-оценка по историческому курсу на момент свапа (utime)
    oracle = getattr(api, "prices", None)
    if oracle is None:
        oracle = PriceOracle(api)
        api.prices = oracle

    def _px(meta: Meta) -> Price:
        return (
            Price()
            if meta is None
            else oracle.at(meta.address, meta.symbol, a.timestamp)
        )

    pin, pout = _px(a.token_in), _px(a.token_out)
    a.token_in.usd, a.token_out.usd = pin.usd, pout.usd
    if pin.usd is not None:
        a.usd_in = a.amount_in * pin.usd
    if pout.usd is not None:
        a.usd_out = a.amount_out * pout.usd
    if a.usd_in is not None and a.usd_out is not None:
        a.usd_net = a.usd_out - a.usd_in
    if pin.usd and pout.usd:
        a.usd_rate = pin.usd / pout.usd  # USD за 1 ед. token_out
    for l in a.legs:
        pli, plo = _px(l.token_in), _px(l.token_out)
        if pli.usd is not None:
            l.usd_in = l.amount_in * pli.usd
        if plo.usd is not None:
            l.usd_out = l.amount_out * plo.usd
    a.price_source = (
        f"in={pin.source or '—'}({pin.ts}); out={pout.source or '—'}({pout.ts})"
    )
    a.price_errors = {k: v for k, v in (("in", pin.error), ("out", pout.error)) if v}
    pton = oracle.at("native", "TON", a.timestamp)
    if pton.usd is not None:
        a.usd_gas_bound = a.gas_bound * pton.usd
        a.usd_gas_refunded = a.gas_refunded * pton.usd
        a.usd_gas_spent = a.gas_spent * pton.usd
        a.usd_total_fees = a.total_fees * pton.usd

    # ---- нетто-изменение балансов из value_flow
    for vf in ev.get("value_flow") or []:
        if norm_addr(_a(vf.get("account"))) != wallet:
            continue
        a.net_ton_change = int(vf.get("ton") or 0) / 1e9
        for jt in vf.get("jettons") or []:
            jm = jt.get("jetton") or {}
            sym = jm.get("symbol") or _a(jm.get("address")) or "?"
            dec = int(jm.get("decimals") if jm.get("decimals") is not None else 9)
            a.net_jetton_change[sym] = int(jt.get("quantity") or 0) / (10**dec)
    if not a.net_ton_change:
        a.net_ton_change = incoming / 1e9 - a.gas_bound
    return a


def parse_swap(tx_or_event_id: str, api: TonAPI | None = None) -> SwapAnalysis:
    """tx_or_event_id — хеш транзакции/трассы ИЛИ event_id (для простого свапа совпадают)."""
    api = api or TonAPI()
    ev = api.event(tx_or_event_id)
    a = normalize(ev, api.trace(tx_or_event_id), api)
    a.tx_hash = tx_or_event_id
    return a


def scan_wallet(
    wallet: str, limit: int = 20, api: TonAPI | None = None
) -> list[SwapAnalysis]:
    """Последние свапы произвольного кошелька (для фонового цикла бота)."""
    api = api or TonAPI()
    out = []
    evs = api.account_events(wallet, limit=limit)
    for ev in (evs if isinstance(evs, list) else evs.get("events", [])):
        if not any(x.get("type") == "JettonSwap" for x in (ev.get("actions") or [])):
            continue
        try:
            a = normalize(ev, api.trace(ev["event_id"]), api)
            a.tx_hash = ev["event_id"]
            out.append(a)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- persistence (SQLite)
DEFAULT_DB = os.environ.get(
    "SWAP_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "swaps.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS swaps (
    tx_hash TEXT PRIMARY KEY, event_id TEXT, ts INTEGER, wallet TEXT, dex TEXT,
    token_in_symbol TEXT, token_in_addr TEXT, token_in_decimals INTEGER,
    token_out_symbol TEXT, token_out_addr TEXT, token_out_decimals INTEGER,
    amount_in REAL, amount_out REAL, rate REAL,
    usd_in REAL, usd_out REAL, usd_net REAL, usd_rate REAL,
    gas_bound REAL, gas_refunded REAL, gas_spent REAL,
    usd_gas_spent REAL, total_fees REAL, usd_total_fees REAL,
    net_ton_change REAL, net_jetton_change TEXT,
    tx_count INTEGER, hops INTEGER, success INTEGER, is_scam INTEGER,
    price_source TEXT, price_errors TEXT, refunds TEXT, legs TEXT, stored_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_swaps_wallet ON swaps(wallet, ts);
CREATE INDEX IF NOT EXISTS idx_swaps_ts ON swaps(ts);
"""

_COLS = (
    "tx_hash,event_id,ts,wallet,dex,token_in_symbol,token_in_addr,token_in_decimals,"
    "token_out_symbol,token_out_addr,token_out_decimals,amount_in,amount_out,rate,"
    "usd_in,usd_out,usd_net,usd_rate,gas_bound,gas_refunded,gas_spent,usd_gas_spent,"
    "total_fees,usd_total_fees,net_ton_change,net_jetton_change,tx_count,hops,"
    "success,is_scam,price_source,price_errors,refunds,legs,stored_at"
)


class SwapStore:
    """SQLite-хранилище разобранных свапов + отчёты (история, PnL)."""

    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_DB
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save(self, a: SwapAnalysis) -> bool:
        d = a.to_dict()
        ti = d.get("token_in") or {}
        to = d.get("token_out") or {}
        row = (
            d["tx_hash"],
            d["event_id"],
            d["timestamp"],
            d["wallet"],
            d["dex"],
            ti.get("symbol"),
            ti.get("address"),
            ti.get("decimals"),
            to.get("symbol"),
            to.get("address"),
            to.get("decimals"),
            d["amount_in"],
            d["amount_out"],
            d["rate"],
            d["usd_in"],
            d["usd_out"],
            d["usd_net"],
            d["usd_rate"],
            d["gas_bound"],
            d["gas_refunded"],
            d["gas_spent"],
            d["usd_gas_spent"],
            d["total_fees"],
            d["usd_total_fees"],
            d["net_ton_change"],
            json.dumps(d["net_jetton_change"], ensure_ascii=False),
            d["tx_count"],
            d["hops"],
            int(bool(d["success"])),
            int(bool(d["is_scam"])),
            d["price_source"],
            json.dumps(d["price_errors"], ensure_ascii=False),
            json.dumps(d["refunds"], ensure_ascii=False),
            json.dumps(d["legs"], ensure_ascii=False),
            int(time.time()),
        )
        q = (
            f"INSERT INTO swaps ({_COLS}) VALUES ({','.join('?' * len(row))}) "
            "ON CONFLICT(tx_hash) DO UPDATE SET ts=excluded.ts, usd_in=excluded.usd_in, "
            "usd_out=excluded.usd_out, usd_net=excluded.usd_net, "
            "usd_gas_spent=excluded.usd_gas_spent, usd_total_fees=excluded.usd_total_fees, "
            "stored_at=excluded.stored_at"
        )
        self.conn.execute(q, row)
        self.conn.commit()
        return True

    def history(self, wallet: str | None = None, limit: int = 50) -> list[dict]:
        if wallet:
            rows = self.conn.execute(
                "SELECT * FROM swaps WHERE wallet=? ORDER BY ts DESC LIMIT ?",
                (wallet, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM swaps ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def density(self, wallet: str | None = None, bucket: str = "hour") -> dict:
        """Плотность свапов: распределение сделок и USD-объёма
        по временным интервалам (bucket: hour|day), часам суток и DEX.
        Плюс метрики концентрации (пиковый интервал, доля топ-3 интервалов)."""
        where = "WHERE wallet=?" if wallet else ""
        params = (wallet,) if wallet else ()
        rows = [
            dict(r)
            for r in self.conn.execute(
                f"SELECT * FROM swaps {where} ORDER BY ts ASC", params
            ).fetchall()
        ]
        if not rows:
            return {
                "wallet": wallet or "все кошельки",
                "swaps": 0,
                "period": "—",
                "bucket": bucket,
                "buckets": [],
                "hour_histogram": [],
                "dex": {},
            }
        step = 3600 if bucket == "hour" else 86400
        fmt = "%Y-%m-%d %H:00" if bucket == "hour" else "%Y-%m-%d"
        agg: dict[int, dict] = {}
        hours = [0] * 24
        dex: dict[str, int] = {}
        for r in rows:
            ts = r["ts"] or 0
            b = agg.setdefault(ts // step, {"swaps": 0, "usd": 0.0})
            b["swaps"] += 1
            b["usd"] += r["usd_in"] or 0.0
            hours[time.gmtime(ts).tm_hour] += 1
            dex[r["dex"] or "?"] = dex.get(r["dex"] or "?", 0) + 1
        buckets = [
            {
                "bucket": time.strftime(fmt, time.gmtime(k * step)),
                "swaps": b["swaps"],
                "usd_volume": round(b["usd"], 4),
            }
            for k, b in sorted(agg.items())
        ]
        n = len(rows)
        span = max(1, (rows[-1]["ts"] - rows[0]["ts"]) // step + 1)
        peak = max(buckets, key=lambda x: x["swaps"])
        top3 = sum(sorted((b["swaps"] for b in buckets), reverse=True)[:3])
        return {
            "wallet": wallet or "все кошельки",
            "swaps": n,
            "period": time.strftime("%Y-%m-%d %H:%M", time.gmtime(rows[0]["ts"]))
            + " → "
            + time.strftime("%Y-%m-%d %H:%M", time.gmtime(rows[-1]["ts"])),
            "bucket": bucket,
            "avg_per_bucket": round(n / span, 2),
            "peak_bucket": peak,
            "top3_share_pct": round(100 * top3 / n, 1),
            "busiest_hour_utc": hours.index(max(hours)),
            "hour_histogram": hours,
            "dex": dex,
            "buckets": buckets,
        }

    def pnl(self, wallet: str | None = None, oracle=None) -> dict:
        where = "WHERE wallet=?" if wallet else ""
        params = (wallet,) if wallet else ()
        rows = [
            dict(r)
            for r in self.conn.execute(
                f"SELECT * FROM swaps {where} ORDER BY ts ASC", params
            ).fetchall()
        ]
        now = int(time.time())
        vol = fees = gas = cost = 0.0
        ton_net = 0.0
        bal: dict[str, dict] = {}
        for r in rows:
            vol += r["usd_in"] or 0.0
            fees += r["usd_total_fees"] or 0.0
            # газ считаем по факту (total_fees трассы) — не зависит от наличия привязанного газа
            gas += (
                r["usd_total_fees"]
                if r["usd_total_fees"] is not None
                else (r["usd_gas_spent"] or 0.0)
            )
            cost += r["usd_net"] or 0.0
            ton_net += r["net_ton_change"] or 0.0
            for sym, v in (json.loads(r["net_jetton_change"] or "{}")).items():
                d = bal.setdefault(sym, {"amount": 0.0, "addr": "", "decimals": 9})
                d["amount"] += v
            for lg in json.loads(r["legs"] or "[]"):
                for side in ("token_in", "token_out"):
                    tm = lg.get(side) or {}
                    if not tm.get("symbol"):
                        continue
                    d = bal.setdefault(
                        tm["symbol"], {"amount": 0.0, "addr": "", "decimals": 9}
                    )
                    if not d["addr"]:
                        d["addr"] = tm.get("address") or ""
                    d["decimals"] = tm.get("decimals") or d["decimals"]
        holdings = []
        total = 0.0
        errors = []

        def _value(sym, amount, addr):
            nonlocal total
            usd = None
            if oracle is not None:
                p = oracle.at(addr, sym, now)
                usd = p.usd
                if usd is None and p.error:
                    errors.append(sym)
            v = usd * amount if usd is not None else None
            if v is not None:
                total += v
            holdings.append(
                {"symbol": sym, "amount": amount, "usd": usd, "usd_value": v}
            )

        if abs(ton_net) > 1e-12:
            _value("TON", ton_net, "native")
        for sym, d in bal.items():
            if abs(d["amount"]) > 1e-12:
                _value(sym, d["amount"], d["addr"])
        period = "—"
        if rows:
            period = (
                time.strftime("%Y-%m-%d", time.gmtime(rows[0]["ts"]))
                + " → "
                + time.strftime("%Y-%m-%d", time.gmtime(rows[-1]["ts"]))
            )
        return {
            "wallet": wallet or "все кошельки",
            "swaps": len(rows),
            "period": period,
            "volume_usd": vol,
            "fees_usd": fees,
            "gas_usd": gas,
            "swap_cost_usd": cost,
            "holdings": holdings,
            "holdings_value_usd": (total if holdings else None),
            "price_errors": sorted(set(errors)),
        }


def format_history(rows: list[dict]) -> str:
    if not rows:
        return "История пуста."
    out = [
        f"📚 История свапов: {len(rows)} записей",
        "",
        f"{'Время (UTC)':19} {'DEX':8} {'Отдано':>20} {'→':^3} {'Получено':>20} {'USD net':>12}",
    ]
    for r in rows:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["ts"])) if r["ts"] else "—"
        ain = f"{_fmt(r['amount_in'])} {r['token_in_symbol'] or '?'}"
        aout = f"{_fmt(r['amount_out'])} {r['token_out_symbol'] or '?'}"
        net = "—" if r["usd_net"] is None else f"{r['usd_net']:+.4f}"
        out.append(
            f"{t:19} {str(r['dex'] or '?'):8} {ain:>20} {'→':^3} {aout:>20} {net:>12}"
        )
    return "\n".join(out)


def format_density(rep: dict) -> str:
    if not rep.get("swaps"):
        return "История пуста — плотность считать нечего."
    lines = [
        "📊 <b>Плотность свапов</b>",
        f"👤 {rep['wallet']}",
        f"🔄 Свапов: <b>{rep['swaps']}</b>",
        f"📅 Период: {rep['period']}",
        f"⏱ Шаг: {rep['bucket']}",
        f"📐 Средняя плотность: <b>{rep['avg_per_bucket']}</b> свапов на интервал",
        f"🔥 Пик: {rep['peak_bucket']['bucket']} — {rep['peak_bucket']['swaps']} свапов "
        f"(${rep['peak_bucket']['usd_volume']:,.2f})",
        f"🎯 Концентрация (топ-3 интервала): {rep['top3_share_pct']}% сделок",
        f"🕐 Самый активный час (UTC): {rep['busiest_hour_utc']}:00",
    ]
    if rep.get("dex"):
        lines += ["", "🌐 <b>По DEX</b>"]
        for d, c in sorted(rep["dex"].items(), key=lambda kv: -kv[1]):
            lines.append(f"• {d}: {c}")
    lines += ["", "⏳ <b>Распределение по интервалам</b>"]
    for b in rep["buckets"]:
        bar = "█" * min(20, b["swaps"])
        lines.append(
            f"{b['bucket']}  {b['swaps']:>4}  {bar:<20}  ${b['usd_volume']:,.2f}"
        )
    return "\n".join(lines)


def format_pnl(rep: dict) -> str:
    lines = [
        "📊 <b>PnL-отчёт (агрегат по свапам)</b>",
        f"👤 {rep['wallet']}",
        f"🔄 Свапов: <b>{rep['swaps']}</b>",
        f"📅 Период: {rep['period']}",
        "",
        f"💵 Объём (USD): <b>${rep['volume_usd']:,.2f}</b>",
        f"💸 Стоимость свапов (slippage + DEX-fee, USD): <b>{rep['swap_cost_usd']:+,.4f}</b>",
        f"⛽ Газ (USD): {rep['gas_usd']:,.4f}",
        f"🧾 Всего сетевых комиссий (USD): {rep['fees_usd']:,.4f}",
    ]
    if rep.get("holdings"):
        lines += ["", "🏦 <b>Нетто-позиции по свапам</b>"]
        for h in rep["holdings"]:
            v = "—" if h["usd_value"] is None else f"${h['usd_value']:,.2f}"
            lines.append(f"• {h['symbol']}: {h['amount']:+,.6f}  ({v})")
    if rep.get("holdings_value_usd") is not None:
        lines += ["", f"💰 <b>Стоимость позиций: ${rep['holdings_value_usd']:,.2f}</b>"]
    if rep.get("price_errors"):
        lines.append(f"⚠️ Без курса: {', '.join(rep['price_errors'])}")
    return "\n".join(lines)


# ---------------------------------------------------------------- bot formatter
def _fmt(x: float, p: int = 6) -> str:
    return f"{x:,.{p}f}".rstrip("0").rstrip(".")


def format_bot_message(a: SwapAnalysis) -> str:
    ts = (
        time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(a.timestamp))
        if a.timestamp
        else "—"
    )
    ti, to = a.token_in, a.token_out
    sharpe = "✅" if a.success else "❌"
    lines = [
        f"🔄 <b>Свап {a.dex.upper()}</b>  {sharpe}",
        f"👤 <code>{a.wallet}</code>",
        f"🕒 {ts}",
        "",
        f"➡️ Отдано: <b>{_fmt(a.amount_in)} {ti.symbol}</b>",
        f"⬅️ Получено: <b>{_fmt(a.amount_out)} {to.symbol}</b>",
    ]
    if a.rate:
        lines.append(
            f"📈 Курс: 1 {ti.symbol} = {_fmt(a.rate, 6)} {to.symbol}"
            f"  (1 {to.symbol} = {_fmt(a.rate_inverse, 6)} {ti.symbol})"
        )
    if a.usd_in is not None or a.usd_out is not None:

        def _usd(x):
            return "—" if x is None else f"${x:,.4f}" if abs(x) < 1 else f"${x:,.2f}"

        lines.append(f"💵 USD: отдано {_usd(a.usd_in)} → получено {_usd(a.usd_out)}")
        if a.usd_net is not None:
            lines.append(
                f"💵 Нетто USD: <b>{'+' if a.usd_net >= 0 else ''}{a.usd_net:,.4f}</b>"
            )
    if a.price_errors:
        for k, v in a.price_errors.items():
            lines.append(f"⚠️ USD({k}): нет курса — {v}")
    if a.hops > 1:
        lines.append(
            f"🔀 Хопов: {a.hops} "
            + " → ".join(l.token_in.symbol + "/" + l.token_out.symbol for l in a.legs)
        )
    lines += [
        "",
        "⛽ <b>Газ</b>",
        f"• Привязано: {_fmt(a.gas_bound)} TON"
        + (f"  (${a.usd_gas_bound:,.4f})" if a.usd_gas_bound is not None else ""),
        f"• Возвращено: <b>{_fmt(a.gas_refunded)} TON</b>"
        + (f"  (${a.usd_gas_refunded:,.4f})" if a.usd_gas_refunded is not None else ""),
        f"• Потрачено: {_fmt(a.gas_spent)} TON"
        + (f"  (${a.usd_gas_spent:,.4f})" if a.usd_gas_spent is not None else ""),
    ]
    for r in a.refunds:
        lines.append(f"   ↩️ {r.kind}: +{_fmt(r.amount)} TON (<code>{r.op}</code>)")
    lines += [
        "",
        "💰 <b>Итог</b>",
        f"• Нетто TON: <b>{'+' if a.net_ton_change >= 0 else ''}{_fmt(a.net_ton_change)}</b>",
    ]
    for sym, v in a.net_jetton_change.items():
        lines.append(f"• Нетто {sym}: {'+' if v >= 0 else ''}{_fmt(v)}")
    lines += [
        f"• Всего газа по трассе: {_fmt(a.total_fees)} TON"
        + (f"  (${a.usd_total_fees:,.4f})" if a.usd_total_fees is not None else "")
        + f" ({a.tx_count} транз.)",
        f"🔗 https://tonviewer.com/transaction/{a.tx_hash}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI
def main(argv: list[str]) -> int:
    args = argv[1:]
    fixture = None
    watch = None
    limit = 20
    as_json = False
    target = None
    usd = True
    db_path = None
    do_store = False
    do_history = False
    do_pnl = False
    do_density = False
    bucket = "hour"
    i = 0
    while i < len(args):
        if args[i] == "--fixture-dir":
            fixture = args[i + 1]
            i += 2
        elif args[i] == "--watch":
            watch = args[i + 1]
            i += 2
        elif args[i] == "--limit":
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--json":
            as_json = True
            i += 1
        elif args[i] == "--no-usd":
            usd = False
            i += 1
        elif args[i] == "--db":
            db_path = args[i + 1]
            i += 2
        elif args[i] == "--store":
            do_store = True
            i += 1
        elif args[i] == "--history":
            do_history = True
            i += 1
        elif args[i] == "--pnl":
            do_pnl = True
            i += 1
        elif args[i] == "--density":
            do_density = True
            i += 1
        elif args[i] == "--bucket":
            bucket = args[i + 1].lower()
            i += 2
        else:
            target = args[i]
            i += 1

    api = TonAPI()
    if not usd:

        class _NoPrice:
            def at(self, addr, symbol, ts):
                return Price()

        api.prices = _NoPrice()
    oracle = getattr(api, "prices", None)
    if oracle is None and usd:
        oracle = PriceOracle(api)
        api.prices = oracle

    store = (
        SwapStore(db_path)
        if (db_path or do_store or do_history or do_pnl or do_density)
        else None
    )

    if do_history:
        rows = store.history(wallet=target, limit=limit)
        print(
            json.dumps(rows, ensure_ascii=False, indent=1)
            if as_json
            else format_history(rows)
        )
        return 0
    if do_pnl:
        rep = store.pnl(wallet=target, oracle=oracle)
        print(
            json.dumps(rep, ensure_ascii=False, indent=1)
            if as_json
            else format_pnl(rep)
        )
        return 0
    if do_density:
        if bucket not in ("hour", "day"):
            print("Ошибка: --bucket должен быть hour или day", file=sys.stderr)
            return 2
        rep = store.density(wallet=target, bucket=bucket)
        print(
            json.dumps(rep, ensure_ascii=False, indent=1)
            if as_json
            else format_density(rep)
        )
        return 0

    try:
        if fixture:
            ev = json.load(open(f"{fixture}/ev.json"))
            tr = json.load(open(f"{fixture}/tr.json"))
            a = normalize(ev, tr, api)
            a.tx_hash = ev.get("event_id", "")
            res = [a]
        elif watch:
            res = scan_wallet(watch, limit=limit, api=api)
            if not res:
                print("Свапов в истории кошелька не найдено.")
                return 0
        elif target:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", target or ""):
                print(
                    f"Ошибка: '{target}' не похож на хеш транзакции TON (нужно 64 hex-символа).\n"
                    f"Для адреса кошелька используйте: --watch <адрес>",
                    file=sys.stderr,
                )
                return 2
            res = [parse_swap(target, api=api)]
        else:
            print(__doc__)
            return 2
    except urllib.error.HTTPError as e:
        print(
            f"Ошибка: TonAPI ответил HTTP {e.code} для '{target or watch}'. "
            f"Проверьте хеш/адрес или повторите позже.",
            file=sys.stderr,
        )
        return 1
    except ValueError as e:
        print(f"Ошибка: {e} (в этом событии нет свапа).", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Ошибка: не удалось разобрать транзакцию — {e}", file=sys.stderr)
        return 1

    for a in res:
        if store is not None and (do_store or db_path):
            store.save(a)
        print(
            json.dumps(a.to_dict(), ensure_ascii=False, indent=1)
            if as_json
            else format_bot_message(a)
        )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
