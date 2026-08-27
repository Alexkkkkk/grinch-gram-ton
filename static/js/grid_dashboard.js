const socket = io();
let mainChart;
let priceData = [], pnlData = [], labels = [];

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
                    label: 'Цена USDT/USDT',
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

    // Update price
    if (data.price) {
        document.getElementById('currentPrice').textContent = '$' + data.price.toFixed(5);
        const pt = document.getElementById('price-ton');
        if (pt) pt.textContent = '$' + data.price.toFixed(2);
        const chg = data.change_24h || 0;
        const el = document.getElementById('priceChange');
        el.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
        el.className = 'price-change ' + (chg >= 0 ? 'positive' : 'negative');
    }

    // Update candlestick chart in real-time
    if (data.candles && candleSeries) {
        const sorted = data.candles.sort((a, b) => a.t - b.t);
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
        candleSeries.setData(chartData);
        volumeSeries.setData(volData);
        candleChart.timeScale().fitContent();
    }
});

// ── Periodic data fetch (non-price data) ─────────────────────────────────────
async function fetchAllData() {
    try {
        const [statusRes, balanceRes, historyRes, v7Res] = await Promise.all([
            fetch('/api/status'),
            fetch('/api/balance'),
            fetch('/api/history?hours=24'),
            fetch('/api/v7/all'),
        ]);

        const status = await statusRes.json();
        const balance = await balanceRes.json();
        const history = await historyRes.json();
        const v7 = await v7Res.json();

        updateStatus(status);
        updateBalance(balance);
        updateCharts(history);
        updateV7(v7);
    } catch (e) {
        console.error('fetch error:', e);
    }
}

function updateStatus(data) {
    document.getElementById('symbol').textContent = data.symbol || 'TON/USDT';

    const sec = data.uptime_sec || 0;
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    document.getElementById('uptime').textContent = d + 'д. ' + h + 'ч. ' + m + 'мин.';
}

function updateBalance(data) {
    if (!data.ok) return;

    const tonEl = document.getElementById('bal-ton');
    if (tonEl) tonEl.textContent = data.ton.amount.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 4});

    const tonUsd = document.getElementById('bal-ton-usd');
    if (tonUsd) tonUsd.textContent = data.ton.usd.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2});

    const priceTon = document.getElementById('price-ton');
    if (priceTon) priceTon.textContent = '$' + data.ton.price.toFixed(2);

    const tokenEl = document.getElementById('bal-token');
    if (tokenEl) tokenEl.textContent = Math.floor(data.token.amount).toLocaleString('ru-RU');

    const tokenUsd = document.getElementById('bal-token-usd');
    if (tokenUsd) tokenUsd.textContent = data.token.usd.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2});

    const tokenTon = document.getElementById('bal-token-ton');
    if (tokenTon) tokenTon.textContent = data.token.price_ton.toFixed(4);

    const priceToken = document.getElementById('price-token');
    if (priceToken) priceToken.textContent = '$' + data.token.price.toFixed(6);

    const tName = document.getElementById('token-name');
    if (tName) tName.textContent = data.token.symbol;

    const tName2 = document.getElementById('token-name-2');
    if (tName2) tName2.textContent = data.token.symbol;

    // Update current price display
    document.getElementById('currentPrice').textContent = '$' + data.token.price.toFixed(5);
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
    // Prophet
    const prophet = v7.prophet || {};
    const pSignal = prophet.signal || 'HOLD';
    const pConf = prophet.confidence || 0;
    const pEl = document.getElementById('prophet-signal');
    pEl.textContent = pSignal;
    pEl.className = 'v7-value v7-signal-' + pSignal.toLowerCase();
    document.getElementById('prophet-target').textContent = 'Target: ' + (prophet.target_price || '—');
    document.getElementById('prophet-conf-bar').style.width = pConf + '%';
    document.getElementById('prophet-conf-bar').className = 'v7-confidence-fill ' + (pConf > 70 ? 'trust-high' : pConf > 40 ? 'trust-mid' : 'trust-low');

    const horizons = prophet.horizons || {};
    const h3 = horizons['3'] || {};
    const h7 = horizons['7'] || {};
    const h14 = horizons['14'] || {};
    document.getElementById('prophet-horizons').textContent =
        '3h: ' + (h3.direction || '—') + ' | 7h: ' + (h7.direction || '—') + ' | 14h: ' + (h14.direction || '—');

    // Sentiment
    const sentiment = v7.sentiment || {};
    const fg = sentiment.fear_greed || {};
    const fgVal = fg.value || 50;
    document.getElementById('fg-value').textContent = Math.round(fgVal);
    document.getElementById('fg-value').style.color = fgVal > 75 ? '#0ecb81' : fgVal > 55 ? '#69f0ae' : fgVal > 45 ? '#f0b90b' : fgVal > 25 ? '#ff9800' : '#f6465d';
    document.getElementById('fg-marker').style.left = fgVal + '%';
    document.getElementById('fg-label').textContent = fg.label || 'Neutral';
    document.getElementById('sentiment-signal').textContent = 'Signal: ' + (sentiment.signal || 'NEUTRAL');

    // Swarm
    const swarm = v7.swarm || {};
    const sConsensus = swarm.consensus || 'HOLD';
    const sEl = document.getElementById('swarm-consensus');
    sEl.textContent = sConsensus;
    sEl.className = 'v7-value v7-signal-' + sConsensus.toLowerCase();
    document.getElementById('swarm-agents').textContent = (swarm.agents_count || 16) + ' agents | Avg fitness: ' + (swarm.avg_fitness || 0).toFixed(3);

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
    document.getElementById('trust-score').textContent = (trust * 100).toFixed(0) + '%';
    document.getElementById('trust-score').style.color = trust > 0.7 ? '#0ecb81' : trust > 0.4 ? '#f0b90b' : '#f6465d';
    document.getElementById('trust-label').textContent = xai.trust_label || 'Waiting...';
    document.getElementById('trust-bar').style.width = (trust * 100) + '%';
    document.getElementById('trust-bar').className = 'v7-confidence-fill ' + (trust > 0.7 ? 'trust-high' : trust > 0.4 ? 'trust-mid' : 'trust-low');

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

function addLog(msg, type) {
    const panel = document.getElementById('logPanel');
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
            fetchCandles();
        });
    });

    fetchCandles(); // initial load
    // setInterval removed — candles update via WebSocket every 2s
    window.addEventListener("resize", () => candleChart.timeScale().fitContent());
}

async function fetchCandles() {
    try {
        const res = await fetch(`/api/candles?timeframe=${currentTimeframe}&limit=300`);
        const data = await res.json();
        let candles = data.candles || [];

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

        candleSeries.setData(chartData);
        volumeSeries.setData(volData);
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
