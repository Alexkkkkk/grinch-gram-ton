"""
MetaEngine — an honest, self-learning decision core for the QuantumGrinch TON/USDT bot.

Layers:
  * LLMReasoner  : OpenAI-compatible LLM (Groq/OpenAI/DeepSeek/Ollama) proposes action + confidence.
  * OutcomeStore : SQLite log of (features, action, reward) from REAL trading outcomes.
  * LinUCB       : contextual bandit that learns from realised reward and re-ranks actions.
  * MetaEngine   : blends the LLM prior with the learned policy and updates ONLINE.
Not fine-tuning, no GPU, no profit guarantee.
"""
from __future__ import annotations
import json, math, os, re, sqlite3, time
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

    def log(self, action: str, reward: float, features: Sequence[float],
            confidence: float = 0.0, meta: Optional[dict] = None):
        with self._conn() as c:
            c.execute("INSERT INTO outcomes(ts,action,reward,confidence,features,meta)"
                      " VALUES(?,?,?,?,?,?)",
                      (time.time(), action, float(reward), float(confidence),
                       json.dumps([float(x) for x in features]), json.dumps(meta or {})))

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]

    def recent(self, n: int = 50):
        with self._conn() as c:
            return c.execute("SELECT ts,action,reward FROM outcomes ORDER BY id DESC LIMIT ?",
                             (n,)).fetchall()


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
    """OpenAI-compatible client — Groq, OpenAI, DeepSeek, Ollama. Robust JSON parsing."""
    def __init__(self, model=None, base_url=None, api_key=None, timeout=25):
        self.model = model or os.getenv("META_LLM_MODEL", "")
        self.base_url = base_url or os.getenv("META_LLM_BASE_URL", "https://api.openai.com/v1")
        self.api_key = api_key or os.getenv("META_LLM_API_KEY", "")
        self.timeout = timeout
        self.last_error = ""
        # Throttle: never hammer the provider (protects the bot's own Groq quota too).
        self.min_interval = float(os.getenv("META_LLM_MIN_INTERVAL_SEC", "120"))
        self.cooldown_sec = float(os.getenv("META_LLM_COOLDOWN_SEC", "600"))
        self._last_call = 0.0
        self._cooldown_until = 0.0
        self._cache = None

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = (text or "").strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        a = re.search(r'"?action"?\s*[:=]\s*"?(BUY|SELL|HOLD)"?', text, re.I)
        c = re.search(r'"?confidence"?\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)', text)
        return {"action": a.group(1).upper() if a else "HOLD",
                "confidence": float(c.group(1)) if c else 0.0, "rationale": ""}

    def propose(self, context: Dict) -> Decision:
        now = time.time()
        if not self.api_key:
            return Decision("HOLD", 0.0, 0.0, "llm:disabled", "no META_LLM_API_KEY")
        # within cooldown after a limit/auth error -> reuse cache, do not call out
        if now < self._cooldown_until:
            if self._cache:
                return self._cache
            return Decision("HOLD", 0.0, 0.0, "llm:cooldown", self.last_error[:200])
        # respect the minimum spacing between real calls -> reuse the cached decision
        if self._cache and (now - self._last_call) < self.min_interval:
            return self._cache
        self._last_call = now
        prompt = (
            "You are a conservative quantitative decision module for a TON/USDT grid bot. "
            "Reply with ONLY one minified JSON object, no markdown, no prose: "
            '{"action":"BUY|SELL|HOLD","confidence":0-100,"rationale":"<=140 chars"}. '
            "HOLD is always valid. Context: " + json.dumps(context, ensure_ascii=False)
        )
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
            last_err = ""
            for use_rf in (True, False):
                try:
                    kwargs = dict(model=self.model,
                                  messages=[{"role": "user", "content": prompt}],
                                  temperature=0.2, max_tokens=400)
                    if use_rf:
                        kwargs["response_format"] = {"type": "json_object"}
                    r = client.chat.completions.create(**kwargs)
                    data = self._extract_json(r.choices[0].message.content)
                    action = str(data.get("action", "HOLD")).upper()
                    if action not in ACTIONS:
                        action = "HOLD"
                    conf = float(data.get("confidence", 0) or 0)
                    self._cache = Decision(action, conf, conf / 100.0, "llm",
                                           str(data.get("rationale", ""))[:200])
                    return self._cache
                except Exception as e:
                    last_err = "%s: %s" % (type(e).__name__, str(e))
                    low = last_err.lower()
                    if "429" in low or "rate limit" in low or "401" in low or "403" in low \
                            or "invalid" in low or "auth" in low:
                        self._cooldown_until = time.time() + self.cooldown_sec
                        self.last_error = last_err
                        if self._cache:
                            return self._cache
                        return Decision("HOLD", 0.0, 0.0, "llm:cooldown", last_err[:200])
            self.last_error = last_err
            return Decision("HOLD", 0.0, 0.0, "llm:error", last_err[:200])
        except Exception as e:
            self.last_error = str(e)
            return Decision("HOLD", 0.0, 0.0, "llm:error", str(e)[:200])


class MetaEngine:
    def __init__(self, dim: int = 6, alpha: float = 0.6, llm_weight: float = 0.35,
                 store_path: str = "meta_memory.sqlite", reasoner: Optional[LLMReasoner] = None):
        self.dim = dim
        self.bandit = LinUCB(len(ACTIONS), dim, alpha)
        self.store = OutcomeStore(store_path)
        self.llm = reasoner or LLMReasoner()
        self.llm_weight = llm_weight
        self._last: Optional[Decision] = None

    def decide(self, features: Sequence[float], context: Optional[Dict] = None,
               use_llm: bool = True) -> Decision:
        x = np.asarray(features, dtype=float)[: self.dim]
        if x.shape[0] < self.dim:
            x = np.pad(x, (0, self.dim - x.shape[0]))
        blend = self.bandit.scores(x)
        llm_d = self.llm.propose(context or {}) if use_llm else Decision("HOLD", 0, 0, "llm:off")
        if llm_d.action in ACTIONS:
            blend[ACTIONS.index(llm_d.action)] += self.llm_weight * llm_d.score
        arm = int(np.argmax(blend))
        d = Decision(ACTIONS[arm], llm_d.confidence, float(blend[arm]), "meta",
                     llm_d.rationale, [float(v) for v in x])
        self._last = d
        return d

    def record_outcome(self, reward: float, features: Optional[Sequence[float]] = None,
                       action: Optional[str] = None, meta: Optional[dict] = None):
        d = self._last
        feats = features if features is not None else (d.features if d else None)
        act = (action or (d.action if d else "HOLD")).upper()
        if feats is None:
            raise ValueError("no features available; pass them explicitly")
        self.bandit.update(ACTIONS.index(act), np.asarray(feats, dtype=float), float(reward))
        self.store.log(act, reward, feats, (d.confidence if d else 0.0), meta)

    def stats(self) -> Dict:
        return {"experiences": self.store.count(),
                "theta": {a: (np.linalg.inv(self.bandit.A[i]) @ self.bandit.b[i]).round(4).tolist()
                          for i, a in enumerate(ACTIONS)}}


if __name__ == "__main__":
    print("MetaEngine ready.")
