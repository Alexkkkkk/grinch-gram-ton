const socket = io();
let mainChart;
let priceData = [], pnlData = [], labels = [];

// Tell server which timeframe we're viewing
function notifyTimeframe(tf) {
    socket.emit('subscribe_timeframe', { timeframe: tf });
}

// ── Web Worker for RSI/MA indicators (non-blocking UI) ──────────────────────
const indicatorWorker = new Worker(URL.createObjectURL(new Blob([`
    self.onmessage = function(e) {
        const { candles, type } = e.data;
        if (type === 'rsi') {
            const rsi = calculateRSI(candles, 14);
            self.postMessage({ type: 'rsi', value: rsi });
        } else if (type === 'ema') {
            const ema = calculateEMA(candles, 20);
            self.postMessage({ type: 'ema', value: ema });
        }
    };
    function calculateRSI(candles, period) {
        if (candles.length < period + 1) return 50;
        let gains = 0, losses = 0;
        for (let i = candles.length - period; i < candles.length; i++) {
            const change = candles[i].close - candles[i-1].close;
            if (change > 0) gains += change; else losses -= change;
        }
        const avgGain = gains / period;
        const avgLoss = losses / period || 0.001;
        const rs = avgGain / avgLoss;
        return 100 - (100 / (1 + rs));
    }
    function calculateEMA(candles, period) {
        if (candles.length < period) return candles[candles.length-1].close;
        const k = 2 / (period + 1);
        let ema = candles[0].close;
        for (let i = 1; i < candles.length; i++) {
            ema = candles[i].close * k + ema * (1 - k);
        }
        return ema;
    }
`], { type: 'application/javascript' })));

indicatorWorker.onmessage = (e) => {
    if (e.data.type === 'rsi') {
        console.log('[Worker] RSI:', e.data.value.toFixed(2));
    } else if (e.data.type === 'ema') {
        console.log('[Worker] EMA20:', e.data.value.toFixed(5));
    }
};

function initCharts() {
    // Main chart: Price + PnL dual axis
    const ctx1 = document.getElementById('mainChart').getContext('2d');
    mainChart = new Chart(ctx1, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Цена GRAM/USD',
                    data: [],
                    borderColor: '#f0b90b',
                    backgroundColor: 'rgba(240, 185, 11, 0.05)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                    yAxisID: 'y',
                },
                {
                    label: 'PnL USDT',
                    data: [],
                    borderColor: '#0ecb81',
                    backgroundColor: 'rgba(14, 203, 129, 0.08)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                    yAxisID: 'y1',
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: {
                    labels: { color: '#848e9c', font: { size: 11 } }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: '#2b3139' },
                    ticks: { color: '#848e9c', font: { size: 10 }, maxTicksLimit: 8 }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: '#2b3139' },
                    ticks: { color: '#f0b90b', font: { size: 10 } }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#0ecb81', font: { size: 10 } }
                }
            }
        }
    });

}

// ── Socket.io Real-Time ──────────────────────────────────────────────────────
socket.on('connect', () => {
    addLog('WebSocket connected', 'info');
});

socket.on('price', (data) => {
    if (data && data.price) {
        document.getElementById('currentPrice').textContent = '$' + data.price.toFixed(5);
        const pt = document.getElementById('price-ton');
        if (pt) pt.textContent = '$' + data.price.toFixed(2);
        updateGridPriceLines(null, data.price);
    }
});

socket.on('status', (data) => {
    if (!data) return;

    // Update price only
    if (data.price) {
        document.getElementById('currentPrice').textContent = '$' + data.price.toFixed(5);
        const pt = document.getElementById('price-ton');
        if (pt) pt.textContent = '$' + data.price.toFixed(2);
        const chg = data.change_24h || 0;
        const el = document.getElementById('priceChange');
        el.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
        el.className = 'price-change ' + (chg >= 0 ? 'positive' : 'negative');
    }
});

// ── Real-time candle updates via dedicated WebSocket event ─────────────────────
let _lastCandleTime = 0;

socket.on('candles', (data) => {
    if (!data || !data.candles || !candleSeries) return;

    // Ignore if timeframe doesn't match current chart
    if (data.timeframe && data.timeframe !== currentTimeframe) return;

    // Normalize fields: API uses "timestamp", WebSocket uses "t"
    const normalized = data.candles.map(c => ({
        t: c.t || c.timestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        volume: c.volume || 0
    })).filter(c => c.t);

    const sorted = normalized.sort((a, b) => a.t - b.t);
    if (sorted.length === 0) return;

    const chartData = sorted.map(c => ({
        time: c.t,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close
    }));
    const volData = sorted.map(c => ({
        time: c.t,
        value: c.volume || 0,
        color: c.close >= c.open ? "rgba(14,203,129,0.4)" : "rgba(246,70,93,0.4)"
    }));

    const lastTime = sorted[sorted.length - 1].t;

    if (_lastCandleTime === 0 || Math.abs(lastTime - _lastCandleTime) > 3600) {
        // Full reset on init or large gap
        candleSeries.setData(chartData);
        volumeSeries.setData(volData);
    } else {
        // Incremental update: compare by last candle time instead of Set for O(1)
        const existing = candleSeries.data() || [];
        const lastExisting = existing.length > 0 ? existing[existing.length - 1].time : 0;

        for (let i = 0; i < chartData.length; i++) {
            const candle = chartData[i];
            const isLast = (i === chartData.length - 1);
            if (candle.time === lastExisting) {
                if (isLast) {
                    candleSeries.update(candle);
                    if (volumeSeries) volumeSeries.update(volData[i]);
                }
            } else if (candle.time > lastExisting) {
                candleSeries.update(candle);
                if (volumeSeries) volumeSeries.update(volData[i]);
            }
        }
    }
    _lastCandleTime = lastTime;
});

// ── Periodic data fetch (non-price data) ─────────────────────────────────────
async function fetchAllData() {
    // Fetch each endpoint independently so one failure doesn't break others
    let status = null, balance = null, history = null, v7 = null;

    try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        status = await res.json();
        updateStatus(status);
    } catch (e) {
        console.error('[fetch] status error:', e);
    }

    try {
        const res = await fetch('/api/balance');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        balance = await res.json();
        updateBalance(balance);
    } catch (e) {
        console.error('[fetch] balance error:', e);
    }

    try {
        const res = await fetch('/api/history?hours=24');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        history = await res.json();
        updateCharts(history);
    } catch (e) {
        console.error('[fetch] history error:', e);
    }

    try {
        const res = await fetch('/api/v7/all');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        v7 = await res.json();
        updateV7(v7);
    } catch (e) {
        console.error('[fetch] v7 error:', e);
    }

    // AI Grid data
    try {
        await fetchAiRecommendation();
    } catch (e) {
        console.error('[fetch] ai recommendation error:', e);
    }

    try {
        await fetchAiStatus();
    } catch (e) {
        console.error('[fetch] ai status error:', e);
    }
}

function updateStatus(data) {
    if (!data) return;
    const symEl = document.getElementById('symbol');
    if (symEl) symEl.textContent = data.symbol || 'GRAM/USD';

    const sec = Number(data.uptime_sec) || 0;
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const uptimeEl = document.getElementById('uptime');
    if (uptimeEl) uptimeEl.textContent = d + 'д. ' + h + 'ч. ' + m + 'мин.';
}

function updateBalance(data) {
    if (!data || !data.ok) return;

    const ton = data.ton || {};
    const token = data.token || {};

    const tonEl = document.getElementById('bal-ton');
    if (tonEl) {
        const amt = Number(ton.amount) || 0;
        tonEl.textContent = amt.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 4});
    }

    const tonUsd = document.getElementById('bal-ton-usd');
    if (tonUsd) {
        const usd = Number(ton.usd) || 0;
        tonUsd.textContent = usd.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    const priceTon = document.getElementById('price-ton');
    if (priceTon) {
        const p = Number(ton.price) || 0;
        priceTon.textContent = p > 0 ? '$' + p.toFixed(2) : '$—';
    }

    const tokenEl = document.getElementById('bal-token');
    if (tokenEl) {
        const amt = Number(token.amount) || 0;
        tokenEl.textContent = amt.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 4});
    }

    const tokenUsd = document.getElementById('bal-token-usd');
    if (tokenUsd) {
        const usd = Number(token.usd) || 0;
        tokenUsd.textContent = usd.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    const tokenTon = document.getElementById('bal-token-ton');
    if (tokenTon) {
        const p = Number(token.price_ton) || 0;
        tokenTon.textContent = p > 0 ? p.toFixed(4) : '—';
    }

    const priceToken = document.getElementById('price-token');
    if (priceToken) {
        const p = Number(token.price) || 0;
        priceToken.textContent = p > 0 ? '$' + p.toFixed(6) : '$—';
    }

    const tName = document.getElementById('token-name');
    if (tName) tName.textContent = token.symbol || 'USDT';

    const tName2 = document.getElementById('token-name-2');
    if (tName2) tName2.textContent = token.symbol || 'USDT';

    // Update current price display (GRAM/USD price comes from ton.price)
    const curPrice = document.getElementById('currentPrice');
    if (curPrice) {
        const p = Number(ton.price) || Number(token.price) || 0;
        curPrice.textContent = p > 0 ? '$' + p.toFixed(5) : '$—';
    }
}

function updateCharts(history) {
    let prices = history.prices || [];
    let pnls = history.pnl || [];

    // Fallback: generate demo data if server returned empty (shouldn't happen now)
    if (prices.length === 0) {
        prices = generateDemoPrices();
        pnls = generateDemoPnL(prices);
    }

    prices = prices.slice(-100);
    pnls = pnls.slice(-100);

    const lbls = prices.map((p) => {
        const d = new Date(p.t * 1000);
        return d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
    });

    mainChart.data.labels = lbls;
    mainChart.data.datasets[0].data = prices.map(p => p.price);
    mainChart.data.datasets[1].data = pnls.map(p => p.pnl);
    mainChart.update('none');
}

function generateDemoPrices() {
    const pts = [];
    let price = 1.0;
    const now = Date.now() / 1000;
    for (let i = 0; i < 100; i++) {
        price *= (1 + (Math.random() - 0.48) * 0.016);
        price = Math.max(0.5, Math.min(2.0, price));
        pts.push({t: now - (100 - i) * 300, price: price});
    }
    return pts;
}

function generateDemoPnL(prices) {
    let pnl = 0;
    return prices.map(p => {
        pnl += (Math.random() - 0.45) * 0.8;
        return {t: p.t, pnl: pnl, price: p.price};
    });
}

// ── v7 Quantum Intelligence ──────────────────────────────────────────────────
function updateV7(v7) {
    if (!v7) return;
    // Prophet
    const prophet = v7.prophet || {};
    const pSignal = prophet.signal || 'HOLD';
    const pConf = prophet.confidence || 0;
    const pEl = document.getElementById('prophet-signal');
    if (pEl) {
        pEl.textContent = pSignal;
        pEl.className = 'v7-value v7-signal-' + pSignal.toLowerCase();
    }
    const pTarget = document.getElementById('prophet-target');
    if (pTarget) pTarget.textContent = 'Target: ' + (prophet.target ? '$' + prophet.target.toFixed(6) : '—');
    const pConfBar = document.getElementById('prophet-conf-bar');
    if (pConfBar) {
        pConfBar.style.width = pConf + '%';
        pConfBar.className = 'v7-confidence-fill ' + (pConf > 70 ? 'trust-high' : pConf > 40 ? 'trust-mid' : 'trust-low');
    }

    const horizons = prophet.horizons || {};
    const h3 = horizons['3'] || {};
    const h7 = horizons['7'] || {};
    const h14 = horizons['14'] || {};
    const pHorizons = document.getElementById('prophet-horizons');
    if (pHorizons) pHorizons.textContent = '3h: ' + (h3.direction || '—') + ' | 7h: ' + (h7.direction || '—') + ' | 14h: ' + (h14.direction || '—');

    // Sentiment
    const sentiment = v7.sentiment || {};
    const fg = sentiment.fear_greed || {};
    const fgVal = fg.value || 50;
    const fgValueEl = document.getElementById('fg-value');
    if (fgValueEl) {
        fgValueEl.textContent = Math.round(fgVal);
        fgValueEl.style.color = fgVal > 75 ? '#0ecb81' : fgVal > 55 ? '#69f0ae' : fgVal > 45 ? '#f0b90b' : fgVal > 25 ? '#ff9800' : '#f6465d';
    }
    const fgMarker = document.getElementById('fg-marker');
    if (fgMarker) fgMarker.style.left = fgVal + '%';
    const fgLabel = document.getElementById('fg-label');
    if (fgLabel) fgLabel.textContent = fg.label || 'Neutral';
    const sentSignal = document.getElementById('sentiment-signal');
    if (sentSignal) sentSignal.textContent = 'Signal: ' + (sentiment.signal || 'NEUTRAL');

    // Swarm
    const swarm = v7.swarm || {};
    const sConsensus = swarm.consensus || 'HOLD';
    const sEl = document.getElementById('swarm-consensus');
    if (sEl) {
        sEl.textContent = sConsensus;
        sEl.className = 'v7-value v7-signal-' + sConsensus.toLowerCase();
    }
    const sAgents = document.getElementById('swarm-agents');
    if (sAgents) sAgents.textContent = (swarm.buy_count + swarm.sell_count + swarm.hold_count || 16) + ' agents | Consensus: ' + (swarm.consensus || 'HOLD');

    // Swarm visual
    const swarmVis = document.getElementById('swarm-visual');
    if (swarmVis && swarm.agent_signals) {
        swarmVis.innerHTML = '';
        swarm.agent_signals.slice(0, 16).forEach((a, i) => {
            const div = document.createElement('div');
            div.className = 'swarm-agent ' + (a.signal || 'hold').toLowerCase();
            div.textContent = (a.signal || 'H')[0];
            div.title = 'Agent ' + i + ': ' + (a.signal || 'HOLD') + ' (' + (a.confidence || 0).toFixed(0) + '%)';
            swarmVis.appendChild(div);
        });
    }

    // XAI Trust
    const xai = v7.xai || {};
    const trust = xai.trust_score || 0;
    const trustScore = document.getElementById('trust-score');
    if (trustScore) {
        trustScore.textContent = (trust * 100).toFixed(0) + '%';
        trustScore.style.color = trust > 0.7 ? '#0ecb81' : trust > 0.4 ? '#f0b90b' : '#f6465d';
    }
    const trustLabel = document.getElementById('trust-label');
    if (trustLabel) trustLabel.textContent = xai.trust_label || 'Waiting...';
    const trustBar = document.getElementById('trust-bar');
    if (trustBar) {
        trustBar.style.width = (trust * 100) + '%';
        trustBar.className = 'v7-confidence-fill ' + (trust > 0.7 ? 'trust-high' : trust > 0.4 ? 'trust-mid' : 'trust-low');
    }

    // Explanation
    const explBox = document.getElementById('xai-explanation');
    if (explBox && xai.explanation) {
        explBox.textContent = xai.explanation;
    }

    // Counterfactuals
    const cfList = document.getElementById('xai-counterfactuals');
    if (cfList && xai.counterfactuals && xai.counterfactuals.length > 0) {
        cfList.innerHTML = '<strong>What-if scenarios:</strong><ul>' +
            xai.counterfactuals.map(c => '<li>' + c.scenario + ' → ' + c.hypothetical_signal + '</li>').join('') +
            '</ul>';
    }
}

// ── Grid Visual ──────────────────────────────────────────────────────────────
function updateGridVisual(levels, currentPrice, upper, lower) {
    const container = document.getElementById('gridVisual');
    if (!container) return;

    // Keep price line, remove old levels
    const priceLine = document.getElementById('priceLine');
    container.querySelectorAll('.grid-level').forEach(e => e.remove());

    if (!levels || levels.length === 0 || !currentPrice) {
        if (priceLine) priceLine.style.top = '50%';
        return;
    }

    const minP = lower || Math.min(...levels.map(l => l.price));
    const maxP = upper || Math.max(...levels.map(l => l.price));
    const range = maxP - minP || 1;

    const pct = 1 - ((currentPrice - minP) / range);
    priceLine.style.top = (Math.max(0.02, Math.min(0.98, pct)) * 100) + '%';
    document.getElementById('priceTag').textContent = currentPrice.toFixed(5);

    levels.forEach(lvl => {
        const el = document.createElement('div');
        el.className = 'grid-level ' + lvl.side + ' ' + (lvl.status || 'active');
        const lvlPct = 1 - ((lvl.price - minP) / range);
        el.style.top = (Math.max(0, Math.min(1, lvlPct)) * 100) + '%';
        const tag = document.createElement('span');
        tag.className = 'level-tag ' + lvl.side;
        tag.textContent = lvl.side[0].toUpperCase() + ' ' + lvl.price.toFixed(5);
        el.appendChild(tag);
        container.appendChild(el);
    });

    // Also draw grid levels as price lines on the candlestick chart
    updateGridPriceLines(levels, currentPrice);
}

// ── Controls ─────────────────────────────────────────────────────────────────
async function startBot() {
    await fetch('/api/start', {method: 'POST'});
    addLog('Бот запущен', 'info');
}

async function stopBot() {
    await fetch('/api/stop', {method: 'POST'});
    addLog('Бот остановлен', 'sell');
}

async function buildGrid() {
    const body = {
        upper: parseFloat(document.getElementById('upperInput').value) || null,
        lower: parseFloat(document.getElementById('lowerInput').value) || null,
        grid_count: parseInt(document.getElementById('gridCount').value) || 40,
        investment: parseFloat(document.getElementById('investment').value) || 1000,
    };
    const res = await fetch('/api/grid/build', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.ok) {
        addLog('Сетка построена: ' + data.levels_count + ' уровней', 'buy');
        updateGridVisual(data.levels, 1.0, body.upper, body.lower);
    } else {
        addLog('Ошибка: ' + (data.error || 'unknown'), 'sell');
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// AI Grid Control
// ═══════════════════════════════════════════════════════════════════════════════

async function aiToggleGrid() {
    try {
        const res = await fetch('/api/grid/ai/toggle', {method: 'POST'});
        const data = await res.json();
        if (data.ok) {
            addLog('AI Control: ' + (data.ai_enabled ? 'ВКЛЮЧЕН' : 'ВЫКЛЮЧЕН'), 'info');
            updateAiToggleButton(data.ai_enabled);
        }
    } catch(e) { console.error(e); }
}

async function aiBuildGrid() {
    try {
        addLog('AI строит сетку...', 'info');
        const res = await fetch('/api/grid/ai/build', {method: 'POST'});
        const data = await res.json();
        if (data.ok) {
            addLog('AI Сетка построена! Шаг: ' + data.step_pct + '%, Режим: ' + data.regime, 'buy');
            if (data.levels) {
                updateGridVisual(data.levels, 1.0, null, null);
            }
        } else {
            addLog('AI Ошибка: ' + (data.error || 'unknown'), 'sell');
        }
    } catch(e) { console.error(e); }
}

async function fetchAiRecommendation() {
    try {
        const res = await fetch('/api/grid/ai/recommendation');
        const data = await res.json();
        if (data.ok && data.recommendation) {
            updateAiDisplay(data.recommendation);
        }
    } catch(e) { console.error(e); }
}

async function fetchAiStatus() {
    try {
        const res = await fetch('/api/grid/ai/status');
        const data = await res.json();
        if (data.ok) {
            updateAiStatus(data);
        }
    } catch(e) { console.error(e); }
}

function updateAiToggleButton(enabled) {
    const btn = document.getElementById('ai-toggle-btn');
    if (btn) {
        btn.textContent = enabled ? 'AI: ON' : 'AI: OFF';
        btn.className = 'ai-btn ' + (enabled ? 'ai-on' : 'ai-off');
    }
}

function updateAiDisplay(r) {
    const panel = document.getElementById('ai-recommendation');
    if (!panel) return;

    const qs = r.quantum_signal || {};
    const signal = qs.signal || 'HOLD';
    const conf = qs.confidence || 0;
    const regime = r.regime || 'UNKNOWN';
    const step = r.optimal_step || '—';
    const risk = r.risk_level || 0;
    const dd = r.drawdown_pct || 0;
    const trap = r.trap || {};
    const pause = r.pause_buying ? 'ДА' : 'Нет';

    const signalClass = 'ai-signal-' + signal.toLowerCase();

    panel.innerHTML = `
        <div class="ai-signal-row">
            <span class="ai-signal-label">Сигнал:</span>
            <span class="ai-signal-value ${signalClass}">${signal} (${Math.round(conf)}%)</span>
        </div>
        <div class="ai-row"><span>Режим рынка:</span><span>${regime}</span></div>
        <div class="ai-row"><span>Оптимальный шаг:</span><span>${typeof step === 'number' ? step.toFixed(1) : step}%</span></div>
        <div class="ai-row"><span>Уровень риска:</span><span class="${risk >= 2 ? 'ai-risk-high' : ''}">${risk}/3</span></div>
        <div class="ai-row"><span>Просадка:</span><span>${dd.toFixed(1)}%</span></div>
        <div class="ai-row"><span>Ловушка:</span><span class="${trap.trap ? 'ai-trap-yes' : ''}">${trap.trap ? 'ДА (' + trap.confidence + '%)' : 'Нет'}</span></div>
        <div class="ai-row"><span>Пауза покупок:</span><span>${pause}</span></div>
    `;
}

function updateAiStatus(data) {
    // Update AI fields in status
    const aiSignal = document.getElementById('ai-signal');
    if (aiSignal) aiSignal.textContent = data.ai_signal || '—';

    const aiConf = document.getElementById('ai-confidence');
    if (aiConf) aiConf.textContent = (data.ai_confidence || 0).toFixed(0) + '%';

    const aiRegime = document.getElementById('ai-regime');
    if (aiRegime) aiRegime.textContent = data.regime || '—';

    const aiTrap = document.getElementById('ai-trap');
    if (aiTrap) aiTrap.textContent = data.ai_trap_detected ? 'ДА' : 'Нет';

    const aiPause = document.getElementById('ai-pause');
    if (aiPause) aiPause.textContent = data.ai_pause_reason || '—';

    updateAiToggleButton(data.ai_enabled);
}

function addLog(msg, type) {
    const panel = document.getElementById('logPanel');
    if (!panel) return;
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + type;
    entry.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    panel.insertBefore(entry, panel.firstChild);
    if (panel.children.length > 40) panel.lastChild.remove();
}

// ── Candlestick Chart (LightweightCharts) ─────────────────────────────────────
let candleChart, candleSeries, volumeSeries;
let currentTimeframe = '15m';
let gridPriceLines = [];

function initCandlestickChart() {
    if (typeof LightweightCharts === "undefined") {
        setTimeout(initCandlestickChart, 300);
        return;
    }
    const el = document.getElementById('candlestick-chart');
    if (!el) return;

    candleChart = LightweightCharts.createChart(el, {
        layout: {
            background: { type: "solid", color: "#0b0e11" },
            textColor: "#848e9c",
            fontFamily: "Inter, system-ui, sans-serif"
        },
        grid: {
            vertLines: { color: "rgba(43,49,57,0.3)" },
            horzLines: { color: "rgba(43,49,57,0.3)" }
        },
        rightPriceScale: {
            borderColor: "rgba(43,49,57,0.6)",
            scaleMargins: { top: 0.1, bottom: 0.2 }
        },
        timeScale: {
            borderColor: "rgba(43,49,57,0.6)",
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 15,
            barSpacing: 8,
            minBarSpacing: 4
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: "#f0b90b", width: 1, style: 2 },
            horzLine: { color: "#f0b90b", width: 1, style: 2 }
        },
        autoSize: true,
        handleScroll: { vertTouchDrag: false },
        handleScale: { axisPressedMouseMove: true }
    });

    candleSeries = candleChart.addCandlestickSeries({
        upColor: "#0ecb81",
        downColor: "#f6465d",
        wickUpColor: "#0ecb81",
        wickDownColor: "#f6465d",
        borderVisible: false,
        priceFormat: { type: "price", precision: 6, minMove: 0.000001 }
    });

    volumeSeries = candleChart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "vol"
    });
    candleChart.priceScale("vol").applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 }
    });

    // Timeframe buttons
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTimeframe = btn.dataset.tf;
            notifyTimeframe(currentTimeframe);
            fetchCandles(true); // force reset
        });
    });

    fetchCandles(true); // initial load with force reset
    notifyTimeframe(currentTimeframe); // tell server our initial timeframe
    setInterval(() => fetchCandles(false), 5000); // HTTP fallback without reset
    window.addEventListener("resize", () => candleChart.timeScale().fitContent());
}

async function fetchCandles(force = false) {
    try {
        const res = await fetch(`/api/candles?timeframe=${currentTimeframe}&limit=300`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        // Normalize fields: API uses "timestamp", WebSocket uses "t"
        let candles = (data.candles || []).map(c => ({
            timestamp: c.timestamp || c.t,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
            volume: c.volume || 0
        }));

        // Fallback: generate demo candles if not enough data
        if (candles.length < 10) {
            const now = Math.floor(Date.now() / 1000);
            const basePrice = candles.length > 0 ? candles[candles.length - 1].close : 1.39;
            const tfSec = { '1c': 1, '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600 };
            const interval = tfSec[currentTimeframe] || 900;
            candles = [];
            for (let i = 50; i >= 0; i--) {
                const t = now - i * interval;
                const change = (Math.random() - 0.5) * 0.02;
                const open = basePrice * (1 + change);
                const close = basePrice * (1 + (Math.random() - 0.5) * 0.02);
                const high = Math.max(open, close) * (1 + Math.random() * 0.01);
                const low = Math.min(open, close) * (1 - Math.random() * 0.01);
                candles.push({ timestamp: t, open, high, low, close, volume: Math.random() * 1000 });
            }
        }

        const sorted = candles.sort((a, b) => a.timestamp - b.timestamp);
        const chartData = sorted.map(c => ({
            time: c.timestamp,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        }));
        const volData = sorted.map(c => ({
            time: c.timestamp,
            value: c.volume || 0,
            color: c.close >= c.open ? "rgba(14,203,129,0.4)" : "rgba(246,70,93,0.4)"
        }));

        if (force) _lastCandleTime = 0; // reset only on explicit force
        if (_lastCandleTime === 0 || Math.abs(sorted[sorted.length - 1].timestamp - _lastCandleTime) > 3600) {
            candleSeries.setData(chartData);
            volumeSeries.setData(volData);
        } else {
            // Incremental update for polling fallback
            const existing = candleSeries.data() || [];
            const lastExisting = existing.length > 0 ? existing[existing.length - 1].time : 0;
            for (let i = 0; i < chartData.length; i++) {
                const candle = chartData[i];
                if (candle.time > lastExisting || (candle.time === lastExisting && i === chartData.length - 1)) {
                    candleSeries.update(candle);
                    if (volumeSeries) volumeSeries.update(volData[i]);
                }
            }
        }
        _lastCandleTime = sorted[sorted.length - 1].timestamp;
        candleChart.timeScale().fitContent();
    } catch (e) {
        console.error('[Candles]', e);
    }
}

function centerLastCandle() {
    if (!candleChart || !candleSeries) return;
    candleChart.timeScale().fitContent();
}

function updateGridPriceLines(levels, currentPrice) {
    if (!candleSeries) return;
    gridPriceLines.forEach(line => candleSeries.removePriceLine(line));
    gridPriceLines = [];
    if (!levels || levels.length === 0) return;
    levels.forEach(lvl => {
        const line = candleSeries.createPriceLine({
            price: lvl.price,
            color: lvl.side === 'buy' ? 'rgba(14, 203, 129, 0.6)' : 'rgba(246, 70, 93, 0.6)',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: lvl.side.toUpperCase() + ' ' + lvl.price.toFixed(5),
        });
        gridPriceLines.push(line);
    });
    if (currentPrice) {
        const currentLine = candleSeries.createPriceLine({
            price: currentPrice,
            color: '#f0b90b',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: currentPrice.toFixed(5),
        });
        gridPriceLines.push(currentLine);
    }
}

// ── Init ───────────────────────────────────────────────────────────────────────
initCharts();
initCandlestickChart();
fetchAllData();
setInterval(fetchAllData, 3000);

// Grid status
fetch('/api/grid/status').then(r => r.json()).then(d => {
    if (d.levels && d.levels.length > 0) {
        updateGridVisual(d.levels, 1.0, null, null);
    }
});
