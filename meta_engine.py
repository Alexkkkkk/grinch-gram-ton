"""
MetaEngine — an honest, self-learning decision core for the QuantumGrinch TON/USDT bot.

What it actually is:
  * LLMReasoner  : an OpenAI-compatible LLM proposes an action + confidence from market context.
  * OutcomeStore : a SQLite log of (features, action, reward) from REAL trading outcomes.
  * LinUCB       : a contextual bandit that learns from realised reward and re-ranks actions.
  * MetaEngine   : blends the LLM prior with the learned policy and updates ONLINE.

What it is NOT: no fine-tuning, no GPU, and it does NOT guarantee profit.
The "learning" is online reward-driven re-ranking of decisions (Li et al. 2010, LinUCB).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

ACTIONS = ("BUY", "SELL", "HOLD")


@dataclass
class Decision:
    action: str
    confidence: float
    score: float
    source: str
    rationale: str = ""
    features: Optional[List[float]] = None


class OutcomeStore:
    """Durable experience memory: every decision and its realised reward."""

    def __init__(self, path: str = "meta_memory.sqlite"):
        self.path = path
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.path)

    def _init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS outcomes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, action TEXT, reward REAL,
                confidence REAL, features TEXT, meta TEXT)""")

    def log(
        self,
        action: str,
        reward: float,
        features: Sequence[float],
        confidence: float = 0.0,
        meta: Optional[dict] = None,
    ):
        with self._conn() as c:
            c.execute(
                "INSERT INTO outcomes(ts,action,reward,confidence,features,meta)"
                " VALUES(?,?,?,?,?,?)",
                (
                    time.time(),
                    action,
                    float(reward),
                    float(confidence),
                    json.dumps([float(x) for x in features]),
                    json.dumps(meta or {}),
                ),
            )

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]

    def recent(self, n: int = 50):
        with self._conn() as c:
            return c.execute(
                "SELECT ts,action,reward FROM outcomes ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()


class LinUCB:
    """Disjoint linear UCB contextual bandit."""

    def __init__(self, n_arms: int, dim: int, alpha: float = 0.6):
        self.alpha, self.dim = alpha, dim
        self.A = [np.identity(dim) for _ in range(n_arms)]
        self.b = [np.zeros(dim) for _ in range(n_arms)]

    def scores(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        out = np.zeros(len(self.A))
        for i in range(len(self.A)):
            Ainv = np.linalg.inv(self.A[i])
            theta = Ainv @ self.b[i]
            out[i] = theta @ x + self.alpha * math.sqrt(max(float(x @ Ainv @ x), 0.0))
        return out

    def update(self, arm: int, x: np.ndarray, reward: float):
        x = np.asarray(x, dtype=float)
        self.A[arm] += np.outer(x, x)
        self.b[arm] += float(reward) * x


class LLMReasoner:
    """OpenAI-compatible client — OpenAI, DeepSeek, Gemini(compat), Groq or local Ollama."""

    def __init__(self, model=None, base_url=None, api_key=None, timeout=20):
        self.model = model or os.getenv("META_LLM_MODEL", "deepseek-flash")
        self.base_url = base_url or os.getenv(
            "META_LLM_BASE_URL", "https://api.deepseek.com/v1"
        )
        self.api_key = api_key or os.getenv("META_LLM_API_KEY", "")
        self.timeout = timeout

    def propose(self, context: Dict) -> Decision:
        if not self.api_key:
            return Decision("HOLD", 0.0, 0.0, "llm:disabled", "no META_LLM_API_KEY")
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
            )
            prompt = (
                "You are a quantitative decision module for a TON/USDT grid bot. "
                "Given the market context JSON, reply ONLY with compact JSON: "
                '{"action":"BUY|SELL|HOLD","confidence":0-100,"rationale":"<=140 chars"}. '
                "Be conservative; HOLD is always valid.\nContext: "
                + json.dumps(context)
            )
            r = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            data = json.loads(r.choices[0].message.content)
            action = str(data.get("action", "HOLD")).upper()
            if action not in ACTIONS:
                action = "HOLD"
            conf = float(data.get("confidence", 0) or 0)
            return Decision(
                action, conf, conf / 100.0, "llm", str(data.get("rationale", ""))[:200]
            )
        except Exception as e:
            return Decision("HOLD", 0.0, 0.0, "llm:error", str(e)[:200])


class MetaEngine:
    def __init__(
        self,
        dim: int = 6,
        alpha: float = 0.6,
        llm_weight: float = 0.35,
        store_path: str = "meta_memory.sqlite",
        reasoner: Optional[LLMReasoner] = None,
    ):
        self.dim = dim
        self.bandit = LinUCB(len(ACTIONS), dim, alpha)
        self.store = OutcomeStore(store_path)
        self.llm = reasoner or LLMReasoner()
        self.llm_weight = llm_weight
        self._last: Optional[Decision] = None

    def decide(
        self,
        features: Sequence[float],
        context: Optional[Dict] = None,
        use_llm: bool = True,
    ) -> Decision:
        x = np.asarray(features, dtype=float)[: self.dim]
        if x.shape[0] < self.dim:
            x = np.pad(x, (0, self.dim - x.shape[0]))
        blend = self.bandit.scores(x)
        llm_d = (
            self.llm.propose(context or {})
            if use_llm
            else Decision("HOLD", 0, 0, "llm:off")
        )
        if llm_d.action in ACTIONS:
            blend[ACTIONS.index(llm_d.action)] += self.llm_weight * llm_d.score
        arm = int(np.argmax(blend))
        d = Decision(
            ACTIONS[arm],
            llm_d.confidence,
            float(blend[arm]),
            "meta",
            llm_d.rationale,
            [float(v) for v in x],
        )
        self._last = d
        return d

    def record_outcome(
        self,
        reward: float,
        features: Optional[Sequence[float]] = None,
        action: Optional[str] = None,
        meta: Optional[dict] = None,
    ):
        """Call when a decision's realised reward is known (e.g. a closed grid trade's PnL)."""
        d = self._last
        feats = features if features is not None else (d.features if d else None)
        act = (action or (d.action if d else "HOLD")).upper()
        if feats is None:
            raise ValueError("no features available; pass them explicitly")
        self.bandit.update(
            ACTIONS.index(act), np.asarray(feats, dtype=float), float(reward)
        )
        self.store.log(act, reward, feats, (d.confidence if d else 0.0), meta)

    def stats(self) -> Dict:
        return {
            "experiences": self.store.count(),
            "theta": {
                a: (np.linalg.inv(self.bandit.A[i]) @ self.bandit.b[i])
                .round(4)
                .tolist()
                for i, a in enumerate(ACTIONS)
            },
        }


if __name__ == "__main__":
    print("MetaEngine ready. Run: python meta_selftest.py")
