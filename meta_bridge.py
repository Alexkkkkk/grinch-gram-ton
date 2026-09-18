"""
meta_bridge.py — additive, flag-gated bridge: QuantumBrain <-> MetaEngine.

Safety contract
---------------
* META_ENGINE unset/"off"     -> this module is a NO-OP. Behaviour is unchanged.
* META_ENGINE=on              -> MetaEngine runs in SHADOW mode. It logs its own
                                 decision beside QuantumBrain's; it does NOT trade.
* META_ENGINE_INFLUENCE=1     -> MetaEngine may override the unified action
                                 (local safety flags — trap_detected / pause_buying
                                 — always win).

Every decision and its realised PnL is persisted to META_DB_PATH (SQLite) and used
to update the LinUCB policy, so the brain learns from real closed trades.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("meta_bridge")

FEATURES = (
    "momentum",
    "prophet_confidence",
    "sentiment_bias",
    "xai_trust",
    "atr_pct",
    "bias",
)


def _flag(name: str, default: str = "off") -> bool:
    return os.getenv(name, default).strip().lower() in ("on", "1", "true", "yes")


class MetaBridge:
    def __init__(self):
        self.enabled = _flag("META_ENGINE")
        self.influence = _flag("META_ENGINE_INFLUENCE")
        self.engine = None
        self.last = None
        self.last_features = None
        self.min_conf = float(os.getenv("META_MIN_CONFIDENCE", "55"))
        self.pnl_scale = float(os.getenv("META_PNL_SCALE_TON", "0.5"))
        if not self.enabled:
            log.info("[MetaBridge] disabled (set META_ENGINE=on to activate)")
            return
        try:
            from meta_engine import MetaEngine

            self.engine = MetaEngine(
                dim=len(FEATURES),
                alpha=float(os.getenv("META_BANDIT_ALPHA", "0.6")),
                llm_weight=float(os.getenv("META_LLM_WEIGHT", "0.35")),
                store_path=os.getenv("META_DB_PATH", "/app/data/meta_memory.sqlite"),
            )
            log.info(
                "[MetaBridge] ENABLED shadow=%s influence=%s db=%s experiences=%d",
                not self.influence,
                self.influence,
                os.getenv("META_DB_PATH", "/app/data/meta_memory.sqlite"),
                self.engine.store.count(),
            )
        except Exception as e:  # never let the bridge break the bot
            self.enabled = False
            log.error("[MetaBridge] init failed, staying disabled: %s", e)

    # ---- feature mapping: QuantumBrain state -> MetaEngine input vector ----
    def features(self, state, prices):
        p = list(prices or [])
        momentum = 0.0
        if len(p) >= 7 and p[-7] > 0:
            momentum = (p[-1] - p[-7]) / p[-7]
        return [
            max(-1.0, min(1.0, momentum * 100.0)),  # 1 momentum
            float(getattr(state, "prophet_confidence", 0.0)) / 100.0,  # 2 prophet conf
            (float(getattr(state, "sentiment_fg", 50.0)) - 50.0)
            / 50.0,  # 3 sentiment bias
            float(getattr(state, "xai_trust", 50.0)) / 100.0,  # 4 xai trust
            float(getattr(state, "atr_pct", 0.0)),  # 5 volatility
            1.0,  # 6 bias term
        ]

    def context(self, state):
        return {
            "price": getattr(state, "price", 0.0),
            "regime": getattr(state, "regime", ""),
            "atr_pct": getattr(state, "atr_pct", 0.0),
            "prophet_signal": getattr(state, "prophet_signal", "HOLD"),
            "prophet_confidence": getattr(state, "prophet_confidence", 0.0),
            "sentiment_signal": getattr(state, "sentiment_signal", "HOLD"),
            "swarm_consensus": getattr(state, "swarm_consensus", "HOLD"),
            "fusion_action": getattr(state, "fusion_action", "WAIT"),
            "fusion_confidence": getattr(state, "fusion_confidence", 0.0),
            "unified_action": getattr(state, "unified_action", "WAIT"),
            "trap_detected": getattr(state, "trap_detected", False),
            "pause_buying": getattr(state, "pause_buying", False),
        }

    def decide(self, state, prices) -> Optional[object]:
        if not (self.enabled and self.engine):
            return None
        try:
            feats = self.features(state, prices)
            d = self.engine.decide(feats, context=self.context(state), use_llm=True)
            self.last, self.last_features = d, feats
            log.info(
                "[MetaEngine] decision=%s conf=%.1f score=%.3f src=%s | brain=%s",
                d.action,
                d.confidence,
                d.score,
                d.source,
                getattr(state, "unified_action", "?"),
            )
            return d
        except Exception as e:
            log.warning("[MetaEngine] decide failed: %s", e)
            return None

    def apply(self, state):
        """Shadow-log by default; override only when influence is enabled."""
        d = self.decide(state, getattr(state, "price_history", []))
        if d is None or not self.influence:
            return
        if getattr(state, "trap_detected", False) or getattr(
            state, "pause_buying", False
        ):
            return  # local safety always wins
        if d.confidence >= self.min_conf and d.source == "meta":
            mapping = {"BUY": "BUILD", "SELL": "WAIT", "HOLD": "WAIT"}
            target = mapping.get(d.action, "WAIT")
            if getattr(state, "unified_action", None) != target:
                log.info(
                    "[MetaEngine] INFLUENCE override: %s -> %s (conf %.1f)",
                    state.unified_action,
                    target,
                    d.confidence,
                )
                state.unified_action = target

    def record_trade(self, pnl_ton: float, extra: Optional[dict] = None):
        if not (self.enabled and self.engine) or self.last is None:
            return
        try:
            reward = max(-1.0, min(1.0, float(pnl_ton) / self.pnl_scale))
            self.engine.record_outcome(
                reward,
                features=self.last_features,
                action=self.last.action,
                meta={"pnl_ton": float(pnl_ton), **(extra or {})},
            )
            log.info(
                "[MetaEngine] learned from trade pnl=%.6f TON -> reward=%+.3f (n=%d)",
                pnl_ton,
                reward,
                self.engine.store.count(),
            )
        except Exception as e:
            log.warning("[MetaEngine] record_trade failed: %s", e)
