# 🤖 QuantumGrinch v7 — AI Trading Bot for TON/USDT

## 🧠 Quantum Intelligence Suite
- **Neural Prophet** — attention-based price prediction (3/7/14 candle horizons)
- **Market Sentiment** — Fear & Greed Index + Order Flow + Divergence
- **Quantum Optimizer** — simulated annealing for grid parameters
- **Swarm Intelligence** — 16 evolving agents with genetic evolution
- **XAI Explainer** — trust scores, counterfactuals, SHAP-like attribution

## ⚡ Trading Pair
**TON/USDT** on DeDust DEX (TON blockchain)

## 🚀 Quick Start
```bash
pip install -r requirements.txt
export TON_MNEMONIC="your 24 words"
export TON_WALLET="your_address"
export TONCENTER_API_KEY="your_key"
python main.py
```

## 📊 Dashboard
Web UI: http://localhost:8080

## 🧬 Architecture
```
┌─────────────────────────────────────────┐
│         Quantum Intelligence Suite       │
│  ┌─────────┐ ┌──────────┐ ┌─────────┐ │
│  │ Neural  │ │ Market   │ │ Swarm   │ │
│  │ Prophet │ │ Sentiment│ │ Intel   │ │
│  └────┬────┘ └────┬─────┘ └────┬────┘ │
│       └───────────┴────────────┘       │
│              BrainFusion v3            │
│         8-source weighted consensus    │
└─────────────────────────────────────────┘
```
