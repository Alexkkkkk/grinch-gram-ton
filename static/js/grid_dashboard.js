const socket = io();
let mainChart;
let priceData = [], pnlData = [], labels = [];
let currentGridLevels = [];
const GRID_SETTINGS_KEY = 'quantumgrinch.grid.settings.v1';
const AI_GRID_SETTING_KEY = 'quantumgrinch.grid.ai-enabled.v1';
const TIMEFRAME_KEY = 'quantumgrinch.grid.timeframe.v1';

// Tell server which timeframe we're viewing
function notifyTimeframe(tf) {
    socket.emit('subscribe_timeframe', { timeframe: tf });
    try { localStorage.setItem(TIMEFRAME_KEY, tf); } catch (e) {}
}

function normalizeInvestmentLabel() {
    const investment = document.getElementById('investment');
    const label = investment && investment.previousElementSibling;
    if (label) label.textContent = 'TON:';
}

// ── Step Profit Calculator ────────────────────────────────────────────────────
let _cachedFee = 0.25; // default DeDust fee %
let _cachedStep = 4.0;  // default grid step %
let _cachedMinOrder = 0.05;
let _cachedGasPerTx = 0.004;
let _cachedGasReserve = 0.3;

async function fetchGridConfig() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) return;
        const cfg = await res.json();
        // /api/config is intentionally flat; support the older nested shape too.
        const fee = Number(cfg.fee_pct ?? cfg.fees?.pct);
        const step = Number(cfg.grid_step ?? cfg.grid?.step_pct);
        const minOrder = Number(cfg.grid_min_order_ton ?? cfg.grid?.min_order_ton);
        const gasPerTx = Number(cfg.grid_gas_per_tx ?? cfg.grid?.gas_per_tx);
        const gasReserve = Number(cfg.grid_gas_reserve_ton ?? cfg.grid?.gas_reserve_ton);
        if (Number.isFinite(fee) && fee >= 0) _cachedFee = fee;
        if (Number.isFinite(step) && step > 0) _cachedStep = step;
        if (Number.isFinite(minOrder) && minOrder >= 0) _cachedMinOrder = minOrder;
        if (Number.isFinite(gasPerTx) && gasPerTx >= 0) _cachedGasPerTx = gasPerTx;
        if (Number.isFinite(gasReserve) && gasReserve >= 0) _cachedGasReserve = gasReserve;
    } catch (e) { /* keep safe defaults */ }
    calculateStepProfit();
}

function calculateStepProfit() {
    const gridCountEl = document.getElementById('gridCount');
    const investmentEl = document.getElementById('investment');
    const profitEl = document.getElementById('stepProfit');
    if (!gridCountEl || !investmentEl || !profitEl) return;

    const gridCount = Number.parseInt(gridCountEl.value, 10);
    const investment = Number.parseFloat(investmentEl.value);
    const nSell = Math.max(1, Math.ceil((Number.isFinite(gridCount) ? gridCount : 40) / 2));
    const requestedBuy = Math.max(1, (Number.isFinite(gridCount) ? gridCount : 40) - nSell);
    profitEl.title = '';
    if (!Number.isFinite(investment) || investment <= 0) {
        profitEl.value = '—';
        profitEl.style.color = '#848e9c';
        return;
    }

    const priceText = document.getElementById('price-ton')?.textContent || '';
    const centerPrice = Number.parseFloat(priceText.replace(/[^0-9.,-]/g, '').replace(',', '.'));
    const upper = Number.parseFloat(document.getElementById('upperInput')?.value);
    const lower = Number.parseFloat(document.getElementById('lowerInput')?.value);
    const configuredStep = Math.max(0, Number(_cachedStep) || 0);
    const fee = Math.min(1, Math.max(0, (Number(_cachedFee) || 0) / 100));
    const availableTon = Math.max(0, investment - Math.max(0, Number(_cachedGasReserve) || 0));
    let sellStep = configuredStep;
    let buyStep = configuredStep;

    if (Number.isFinite(centerPrice) && centerPrice > 0 && Number.isFinite(upper) && upper > centerPrice) {
        sellStep = (Math.pow(upper / centerPrice, 1 / nSell) - 1) * 100;
    }

    // GridTrader removes buy levels that cannot cover fees and two gas spends.
    // Iterate because an explicit lower bound changes buyStep when the count changes.
    let effectiveBuy = requestedBuy;
    for (let i = 0; i < 4; i += 1) {
        if (Number.isFinite(centerPrice) && centerPrice > 0 && Number.isFinite(lower) && lower > 0 && lower < centerPrice) {
            buyStep = (Math.pow(centerPrice / lower, 1 / Math.max(1, effectiveBuy)) - 1) * 100;
        } else {
            buyStep = configuredStep;
        }
        const step = Math.max(0, sellStep, buyStep);
        const cycleFactor = (1 + step / 100) * Math.pow(1 - fee, 2) - 1;
        if (cycleFactor <= 0) {
            effectiveBuy = 0;
            break;
        }
        const breakEvenOrder = Math.max(
            Number(_cachedMinOrder) || 0,
            (2 * (Number(_cachedGasPerTx) || 0)) / cycleFactor
        );
        const affordableBuy = breakEvenOrder > 0
            ? Math.floor((availableTon + 1e-9) / breakEvenOrder)
            : requestedBuy;
        const nextBuy = Math.min(requestedBuy, Math.max(0, affordableBuy));
        if (nextBuy === effectiveBuy) break;
        effectiveBuy = nextBuy;
    }

    const step = Math.max(0, sellStep, buyStep);
    const cycleFactor = (1 + step / 100) * Math.pow(1 - fee, 2) - 1;
    if (effectiveBuy <= 0 || cycleFactor <= 0) {
        profitEl.value = '—';
        profitEl.style.color = '#848e9c';
        profitEl.title = 'Недостаточно TON для прибыльного buy-уровня';
        return;
    }

    const profitTon = (investment / effectiveBuy) * cycleFactor;
    const priceTon = Number.isFinite(centerPrice) && centerPrice > 0 ? centerPrice : 1.4;
    const profitUsdt = profitTon * priceTon;
    profitEl.value = '+' + profitTon.toFixed(4) + ' TON  (+$' + profitUsdt.toFixed(2) + ')';
    if (effectiveBuy < requestedBuy) {
        profitEl.title = `Backend сократит buy-уровни: ${effectiveBuy} из ${requestedBuy}`;
    }
    profitEl.style.color = '#0ecb81';
}

function attachProfitCalculator() {
    fetchGridConfig();
    ['gridCount', 'investment', 'upperInput', 'lowerInput'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', calculateStepProfit);
    });
    // Also recalculate when price updates
    const priceObserver = new MutationObserver(calculateStepProfit);
    const priceEl = document.getElementById('price-ton');
    if (priceEl) priceObserver.observe(priceEl, { childList: true, subtree: true });
    calculateStepProfit();
}

function restoreGridSettings() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(GRID_SETTINGS_KEY) || '{}'); } catch (e) {}
    ['upperInput', 'lowerInput', 'gridCount', 'investment'].forEach(id => {
        const input = document.getElementById(id);
        if (input && Object.prototype.hasOwnProperty.call(saved, id)) {
            input.value = saved[id];
        }
        if (input) input.addEventListener('input', persistGridSettings);
    });
    // Attach profit calculator to all grid inputs
    attachProfitCalculator();
}

function persistGridSettings() {
    const settings = {};
    ['upperInput', 'lowerInput', 'gridCount', 'investment'].forEach(id => {
        const input = document.getElementById(id);
        if (input) settings[id] = input.value;
    });
    try { localStorage.setItem(GRID_SETTINGS_KEY, JSON.stringify(settings)); } catch (e) {}
}

function normalizeTimeframeButtons() {
    // Keep older cached HTML compatible with the canonical timeframe keys.
    const secondButton = document.querySelector('.tf-btn[data-tf="1c"]');
    if (secondButton) secondButton.dataset.tf = '1s';

    // Older templates contained both 1М and 1мин, although both meant 1m.
    const legacyMinute = Array.from(document.querySelectorAll('.tf-btn[data-tf="1m"]'))
        .find(button => button.textContent.trim() === '1М');
    const readableMinute = Array.from(document.querySelectorAll('.tf-btn[data-tf="1m"]'))
        .find(button => button.textContent.trim() === '1мин');
    if (legacyMinute && readableMinute) legacyMinute.remove();
}

function restoreTimeframe() {
    let saved = '15m';
    try { saved = localStorage.getItem(TIMEFRAME_KEY) || saved; } catch (e) {}
    if (saved === '1c') saved = '1s';
    const button = document.querySelector(`.tf-btn[data-tf="${saved}"]`);
    if (button) {
        document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
        button.classList.add('active');
        currentTimeframe = saved;
    }
}

function persistAiPreference(enabled) {
    try { localStorage.setItem(AI_GRID_SETTING_KEY, enabled ? 'true' : 'false'); } catch (e) {}
}

function getSavedAiPreference() {
    try {
        const value = localStorage.getItem(AI_GRID_SETTING_KEY);
        return value === null ? null : value === 'true';
    } catch (e) {
        return null;
    }
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
                    label: 'Цена TON/USDT',
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
function updateMarketDataStatus(source, stale = false, available = true) {
    const el = document.getElementById('marketDataStatus');
    if (!el) return;
    if (!available) {
        el.textContent = 'market data: unavailable';
        el.style.color = '#f6465d';
        return;
    }
    el.textContent = `market data: ${source || 'exchange'}${stale ? ' · stale' : ' · live'}`;
    el.style.color = stale ? '#f0b90b' : '#69f0ae';
}

socket.on('connect', () => {
    addLog('WebSocket connected', 'info');
});

socket.on('price', (data) => {
    if (data && data.price) {
        document.getElementById('currentPrice').textContent = '$' + data.price.toFixed(5);
        const pt = document.getElementById('price-ton');
        if (pt) pt.textContent = '$' + data.price.toFixed(2);
        updateGridPriceLines(null, data.price);
        updateMarketDataStatus(data.source, false, true);
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
        updateMarketDataStatus(data.source, Boolean(data.stale), true);
    }
});

// ── Real-time candle updates via dedicated WebSocket event ─────────────────────
let _lastCandleTime = 0;
let _renderedTimeframe = null;

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

    if (_renderedTimeframe !== currentTimeframe || _lastCandleTime === 0) {
        // Full reset on init or after a timeframe change
        candleSeries.setData(chartData);
        volumeSeries.setData(volData);
    } else {
        // Incremental update: compare by last candle time instead of Set for O(1)
        const lastExisting = _lastCandleTime;

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
    _renderedTimeframe = currentTimeframe;
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

    try {
        const res = await fetch('/api/grid/status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const grid = await res.json();
        if (Array.isArray(grid.levels)) {
            updateGridVisual(
                grid.levels,
                Number(grid.current_price ?? grid.center_price) || null,
                grid.upper_price,
                grid.lower_price
            );
        }
    } catch (e) {
        console.error('[fetch] grid error:', e);
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
    if (symEl) symEl.textContent = data.symbol || 'TON/USDT';

    const market = data.market_data || {};
    updateMarketDataStatus(market.source, Boolean(market.stale), market.available !== false);

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

    // Update current price display (TON/USDT price comes from ton.price)
    const curPrice = document.getElementById('currentPrice');
    if (curPrice) {
        const p = Number(ton.price) || Number(token.price) || 0;
        curPrice.textContent = p > 0 ? '$' + p.toFixed(5) : '$—';
    }
}

function updateCharts(history) {
    let prices = history.prices || [];
    let pnls = history.pnl || [];

    // Empty means unavailable; never show invented market data.
    if (prices.length === 0) {
        mainChart.data.labels = [];
        mainChart.data.datasets[0].data = [];
        mainChart.data.datasets[1].data = [];
        mainChart.update('none');
        return;
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
function updateGridVisual(levels, currentPrice) {
    const container = document.getElementById('gridVisual');
    if (!container) return;

    // Keep the last known levels when only the live price changes. The chart
    // itself is the source of truth for vertical placement: price lines are
    // anchored to the candlestick price scale, not to a percentage of the
    // container height (which changes with each timeframe's auto-scale).
    if (Array.isArray(levels)) {
        currentGridLevels = levels
            .map(lvl => ({...lvl, price: Number(lvl.price ?? lvl.price_ton)}))
            .filter(lvl => Number.isFinite(lvl.price) && lvl.price > 0);
    }

    const priceLine = document.getElementById('priceLine');
    if (priceLine) {
        priceLine.style.display = 'none';
        priceLine.style.top = '50%';
    }
    updateGridPriceLines(null, Number(currentPrice) || null);
}

// ── Controls ─────────────────────────────────────────────────────────────────
async function startBot() {
    try {
        const res = await fetch('/api/start', {method: 'POST'});
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
        addLog('Бот запущен', 'info');
        await fetchAllData();
    } catch (e) {
        addLog('Не удалось запустить: ' + e.message, 'sell');
    }
}

async function stopBot() {
    try {
        const res = await fetch('/api/stop', {method: 'POST'});
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
        addLog('Бот остановлен', 'sell');
        await fetchAllData();
    } catch (e) {
        addLog('Не удалось остановить: ' + e.message, 'sell');
    }
}

async function buildGrid() {
    const body = getGridSettings();
    const res = await fetch('/api/grid/build', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.ok) {
        addLog('Сетка построена: ' + data.levels_count + ' уровней', 'buy');
        updateGridVisual(data.levels, data.center_price, data.upper_price, data.lower_price);
    } else {
        addLog('Ошибка: ' + (data.error || 'unknown'), 'sell');
    }
}

function getGridSettings() {
    const settings = {
        upper: parseFloat(document.getElementById('upperInput').value) || null,
        lower: parseFloat(document.getElementById('lowerInput').value) || null,
        grid_count: parseInt(document.getElementById('gridCount').value) || 40,
        investment: parseFloat(document.getElementById('investment').value) || 1000,
    };
    persistGridSettings();
    return settings;
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
            persistAiPreference(data.ai_enabled);
            updateAiToggleButton(data.ai_enabled);
        }
    } catch(e) { console.error(e); }
}

async function aiBuildGrid() {
    const button = document.querySelector('.ai-build');
    if (button) button.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        addLog('AI строит сетку...', 'info');
        const res = await fetch('/api/grid/ai/build', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(getGridSettings()),
            signal: controller.signal
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        if (data.ok) {
            addLog('AI Сетка построена! Шаг: ' + data.step_pct + '%, Режим: ' + data.regime, 'buy');
            if (data.warning) addLog(data.warning, 'info');
            if (data.levels) {
                updateGridVisual(data.levels, data.price || null, data.upper_price, data.lower_price);
            }
        } else {
            addLog('AI Ошибка: ' + (data.error || 'unknown'), 'sell');
        }
    } catch(e) {
        const message = e.name === 'AbortError'
            ? 'таймаут ответа сервера'
            : (e.message || 'неизвестная ошибка');
        addLog('AI Ошибка: ' + message, 'sell');
        console.error(e);
    } finally {
        clearTimeout(timeout);
        if (button) button.disabled = false;
    }
}

async function applyKimiGrid() {
    const button = document.getElementById('kimi-apply-btn');
    if (button) button.disabled = true;
    try {
        addLog('Применяю план Kimi к сетке...', 'info');
        const res = await fetch('/api/grid/ai/apply-kimi', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        if (data.ok) {
            addLog(`Kimi: сетка обновлена — ${data.sell_levels} SELL / ${data.buy_levels} BUY, шаг ${Number(data.step_pct).toFixed(1)}%`, 'buy');
            if (data.levels) {
                updateGridVisual(data.levels, data.price || null, data.upper_price, data.lower_price);
            }
            await fetchAllData();
        }
    } catch (e) {
        addLog('Kimi: не удалось применить план — ' + (e.message || 'ошибка'), 'sell');
    } finally {
        if (button) button.disabled = false;
        await fetchAiRecommendation();
    }
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
            const saved = getSavedAiPreference();
            if (saved !== null && saved !== Boolean(data.ai_enabled)) {
                const toggle = await fetch('/api/grid/ai/toggle', {method: 'POST'});
                const toggled = await toggle.json();
                if (toggled.ok) {
                    persistAiPreference(toggled.ai_enabled);
                    updateAiToggleButton(toggled.ai_enabled);
                }
            }
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

function escapeAiHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function updateAiDisplay(r) {
    const panel = document.getElementById('ai-recommendation');
    if (!panel) return;

    const qs = r.quantum_signal || {};
    const signal = qs.signal || 'HOLD';
    const conf = Number(qs.confidence) || 0;
    const regime = r.regime || 'UNKNOWN';
    const step = Number(r.optimal_step);
    const risk = Number(r.risk_level) || 0;
    const dd = Number(r.drawdown_pct) || 0;
    const trap = r.trap || {};
    const pause = r.pause_buying ? 'ДА' : 'Нет';
    const kimi = r.kimi || {};
    const wallet = kimi.wallet || {};
    const kimiReady = Boolean(kimi.ready);
    const kimiAction = kimi.action || 'WAIT';
    const kimiSignal = kimi.signal || 'HOLD';
    const kimiConf = Number(kimi.confidence) || 0;
    const kimiStep = Number(kimi.step_pct);
    const kimiInvestment = Number(kimi.investment_ton);
    const sellLevels = Number(kimi.sell_levels) || 0;
    const buyLevels = Number(kimi.buy_levels) || 0;
    const walletTon = Number(wallet.ton);
    const walletToken = Number(wallet.token);
    const reason = kimi.reason || (kimi.error ? 'Kimi временно недоступна' : 'Ожидание первого решения Kimi');
    const signalClass = 'ai-signal-' + signal.toLowerCase();
    const kimiSignalClass = 'ai-signal-' + kimiSignal.toLowerCase();
    const applyButton = document.getElementById('kimi-apply-btn');
    if (applyButton) applyButton.disabled = !kimiReady;

    panel.innerHTML = `
        <div class="ai-kimi-card ${kimiReady ? 'is-ready' : 'is-waiting'}">
          <div class="ai-kimi-heading"><span>✦ KIMI GRID PILOT</span><span class="ai-kimi-pill">${kimiReady ? 'ONLINE' : 'WAITING'}</span></div>
          <div class="ai-kimi-grid">
            <div><span>Решение</span><strong>${escapeAiHtml(kimiAction)}</strong></div>
            <div><span>Сигнал</span><strong class="${kimiSignalClass}">${escapeAiHtml(kimiSignal)} ${Math.round(kimiConf)}%</strong></div>
            <div><span>Шаг</span><strong>${Number.isFinite(kimiStep) ? kimiStep.toFixed(1) : '—'}%</strong></div>
            <div><span>Инвестиция</span><strong>${Number.isFinite(kimiInvestment) ? kimiInvestment.toFixed(2) : '—'} TON</strong></div>
            <div><span>Уровни</span><strong>${sellLevels} SELL / ${buyLevels} BUY</strong></div>
            <div><span>Кошелёк</span><strong>${Number.isFinite(walletTon) ? walletTon.toFixed(2) : '—'} TON · ${Number.isFinite(walletToken) ? walletToken.toFixed(0) : '—'} token</strong></div>
          </div>
          <div class="ai-kimi-note">${escapeAiHtml(reason)}</div>
        </div>
        <div class="ai-signal-row">
            <span class="ai-signal-label">Локальный сигнал:</span>
            <span class="ai-signal-value ${signalClass}">${escapeAiHtml(signal)} (${Math.round(conf)}%)</span>
        </div>
        <div class="ai-row"><span>Режим рынка:</span><span>${escapeAiHtml(regime)}</span></div>
        <div class="ai-row"><span>Локальный шаг:</span><span>${Number.isFinite(step) ? step.toFixed(1) : '—'}%</span></div>
        <div class="ai-row"><span>Уровень риска:</span><span class="${risk >= 2 ? 'ai-risk-high' : ''}">${risk}/3</span></div>
        <div class="ai-row"><span>Просадка:</span><span>${dd.toFixed(1)}%</span></div>
        <div class="ai-row"><span>Ловушка:</span><span class="${trap.trap ? 'ai-trap-yes' : ''}">${trap.trap ? 'ДА (' + trap.confidence + '%)' : 'Нет'}</span></div>
        <div class="ai-row"><span>Пауза покупок:</span><span>${pause}</span></div>
    `;
}

function updateAiStatus(data) {
    const aiSignal = document.getElementById('ai-signal');
    if (aiSignal) aiSignal.textContent = data.ai_signal || '—';

    const aiConf = document.getElementById('ai-confidence');
    if (aiConf) aiConf.textContent = (Number(data.ai_confidence) || 0).toFixed(0) + '%';

    const aiRegime = document.getElementById('ai-regime');
    if (aiRegime) aiRegime.textContent = data.regime || '—';

    const aiTrap = document.getElementById('ai-trap');
    if (aiTrap) aiTrap.textContent = data.ai_trap_detected ? 'ДА' : 'Нет';

    const aiPause = document.getElementById('ai-pause');
    if (aiPause) aiPause.textContent = data.ai_pause_reason || '—';

    const kimi = data.kimi || {};
    const wallet = kimi.wallet || {};
    const kimiStatus = document.getElementById('kimi-status');
    if (kimiStatus) {
        kimiStatus.textContent = kimi.ready
            ? `${kimi.action || 'WAIT'} · ${kimi.model || 'Kimi'}`
            : (kimi.error ? 'Недоступна: ' + kimi.error : 'Ожидание ответа');
    }
    const walletTon = document.getElementById('kimi-wallet-ton');
    if (walletTon) walletTon.textContent = Number.isFinite(Number(wallet.ton)) ? Number(wallet.ton).toFixed(2) + ' TON' : '—';
    const kimiPlan = document.getElementById('kimi-plan');
    if (kimiPlan) kimiPlan.textContent = kimi.ready
        ? `${Number(kimi.step_pct || 0).toFixed(1)}% · ${kimi.sell_levels || 0}/${kimi.buy_levels || 0}`
        : '—';
    const applyButton = document.getElementById('kimi-apply-btn');
    if (applyButton) applyButton.disabled = !kimi.ready;

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
let _candleRequestId = 0;
let gridPriceLines = [];

function resetCandleChart() {
    _lastCandleTime = 0;
    _renderedTimeframe = null;
    if (candleSeries) candleSeries.setData([]);
    if (volumeSeries) volumeSeries.setData([]);
}

function applyTimeframeScale() {
    if (!candleChart) return;
    candleChart.timeScale().applyOptions({
        timeVisible: true,
        secondsVisible: currentTimeframe === '1s'
    });
}

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
        visible: false,
        scaleMargins: { top: 0.85, bottom: 0 }
    });

    // Timeframe buttons
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTimeframe = btn.dataset.tf;
            resetCandleChart();
            applyTimeframeScale();
            notifyTimeframe(currentTimeframe);
            fetchCandles(true); // force reset
        });
    });

    applyTimeframeScale();
    fetchCandles(true); // initial load with force reset
    notifyTimeframe(currentTimeframe); // tell server our initial timeframe
    setInterval(() => fetchCandles(false), 5000); // HTTP fallback without reset
    window.addEventListener("resize", () => candleChart.timeScale().fitContent());
}

async function fetchCandles(force = false) {
    const timeframeAtRequest = currentTimeframe;
    const requestId = ++_candleRequestId;
    try {
        const res = await fetch(`/api/candles?timeframe=${encodeURIComponent(timeframeAtRequest)}&limit=300`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        // A slower response from the previous timeframe must never overwrite
        // the chart after the user has already selected a new one.
        if (requestId !== _candleRequestId || timeframeAtRequest !== currentTimeframe) return;
        // Normalize fields: API uses "timestamp", WebSocket uses "t"
        let candles = (data.candles || []).map(c => ({
            timestamp: c.timestamp || c.t,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
            volume: c.volume || 0
        }));

        if (candles.length === 0) {
            console.warn('[Candles] Exchange returned no real candles');
            candleSeries.setData([]);
            volumeSeries.setData([]);
            _lastCandleTime = 0;
            _renderedTimeframe = null;
            return;
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

        if (force || _renderedTimeframe !== timeframeAtRequest || _lastCandleTime === 0) {
            _lastCandleTime = 0;
            candleSeries.setData(chartData);
            volumeSeries.setData(volData);
        } else {
            // Incremental update for polling fallback. Lightweight Charts does
            // not expose a data() reader on series; use our last rendered bar.
            const lastExisting = _lastCandleTime;
            for (let i = 0; i < chartData.length; i++) {
                const candle = chartData[i];
                if (candle.time > lastExisting || (candle.time === lastExisting && i === chartData.length - 1)) {
                    candleSeries.update(candle);
                    if (volumeSeries) volumeSeries.update(volData[i]);
                }
            }
        }
        _lastCandleTime = sorted[sorted.length - 1].timestamp;
        _renderedTimeframe = timeframeAtRequest;
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
    if (Array.isArray(levels)) {
        currentGridLevels = levels
            .map(lvl => ({...lvl, price: Number(lvl.price ?? lvl.price_ton)}))
            .filter(lvl => Number.isFinite(lvl.price) && lvl.price > 0);
    }
    const visibleLevels = currentGridLevels;
    gridPriceLines.forEach(line => candleSeries.removePriceLine(line));
    gridPriceLines = [];
    if ((!visibleLevels || visibleLevels.length === 0) && !currentPrice) return;
    (visibleLevels || []).forEach(lvl => {
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
normalizeInvestmentLabel();
restoreGridSettings();
normalizeTimeframeButtons();
restoreTimeframe();
initCharts();
initCandlestickChart();
fetchAllData();
setInterval(fetchAllData, 3000);

// Grid status
fetch('/api/grid/status').then(r => r.json()).then(d => {
    if (d.levels && d.levels.length > 0) {
        updateGridVisual(
            d.levels,
            Number(d.current_price ?? d.center_price) || null,
            d.upper_price,
            d.lower_price
        );
    }
});
