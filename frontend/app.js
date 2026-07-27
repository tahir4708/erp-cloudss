const $ = (id) => document.getElementById(id);

const els = {
  btn: $("analyzeBtn"),
  symbolId: $("symbolId"),
  instrumentSearch: $("instrumentSearch"),
  instrumentList: $("instrumentList"),
  quotePair: $("quotePair"),
  quotePrice: $("quotePrice"),
  quoteChange: $("quoteChange"),
  exnessBlock: $("exnessQuoteBlock"),
  spotBlock: $("spotQuoteBlock"),
  quoteSpotSym: $("quoteSpotSym"),
  quoteSpotPrice: $("quoteSpotPrice"),
  quoteSpotDiff: $("quoteSpotDiff"),
  quoteExnessSym: $("quoteExnessSym"),
  quoteExnessPrice: $("quoteExnessPrice"),
  quoteDiff: $("quoteDiff"),
  priceSource: $("priceSource"),
  priceSourceWrap: $("priceSourceWrap"),
  mode: $("mode"),
  interval: $("interval"),
  balance: $("balance"),
  risk: $("risk"),
  live: $("liveStatus"),
  board: $("signalBoard"),
  detail: $("detailGrid"),
  side: $("sideValue"),
  entry: $("entryValue"),
  timeframe: $("timeframeValue"),
  lot: $("lotValue"),
  sl: $("slValue"),
  tp: $("tpValue"),
  win: $("winValue"),
  conf: $("confNote"),
  rr: $("rrNote"),
  slNote: $("slNote"),
  riskNote: $("riskNote"),
  reasons: $("reasonList"),
  votes: $("voteList"),
  votesTitle: $("votesTitle"),
  snap: $("snapList"),
  edge: $("edgeNote"),
  disclaimer: $("disclaimer"),
  caption: $("chartCaption"),
  toast: $("toast"),
  core: $("signalCore"),
  chart: $("priceChart"),
};

let lastSignal = null;
let fetching = false;
let symbolCatalog = [];
let symbolFilter = "";
const POPULAR_SYMBOL_IDS = [
  "BINANCE:BTCUSDT",
  "BINANCE:ETHUSDT",
  "BINANCE:PAXGUSDT",
  "BINANCE:XAUTUSDT",
  "BINANCE:XAGUSDT",
  "EXNESS:XAUUSDm",
  "EXNESS:XAGUSDm",
  "EXNESS:BTCUSDm",
  "YAHOO:GC=F",
];

let symbolSearchTimer = null;
let highlightIndex = -1;

let chart = null;
let candleSeries = null;
let volumeSeries = null;
let priceLines = [];
let fitNext = true;

// Live chart when the instrument has a Binance pair (crypto + gold/PAXG).
const INTERVAL_SECONDS = {
  "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
  "1h": 3600, "4h": 14400, "1d": 86400,
};
let tickerTimer = null;
let lastBarTime = 0;
let lastChartClose = 0;
let lastBar = null;
let lastUiTickMs = 0;
let liveSource = "";

const EXNESS_BASE_KEYS = new Set(["XAUUSD", "XAGUSD", "BTCUSD"]);
const SPOT_BASE_KEYS = new Set(["XAUUSD", "XAGUSD", "USOIL"]);

function isSpotBaseKey(key) {
  return SPOT_BASE_KEYS.has((key || "").toUpperCase());
}

const VENUE_CLASS = { BINANCE: "binance", EXNESS: "exness", YAHOO: "yahoo" };

function venueBadge(venue) {
  const cls = VENUE_CLASS[venue] || "binance";
  return `<span class="venue-badge ${cls}">${venue}</span>`;
}

function isExnessBaseKey(key) {
  return EXNESS_BASE_KEYS.has((key || "").toUpperCase());
}

function currentSymbolId() {
  return els.symbolId?.value || "BINANCE:BTCUSDT";
}

function symbolMeta(id) {
  return symbolCatalog.find((s) => s.id === id) || null;
}

function currentMeta() {
  return symbolMeta(currentSymbolId());
}

function syncPriceSourceUi() {
  const meta = currentMeta();
  const venue = meta?.venue || "BINANCE";
  const showExnessOption = venue !== "EXNESS" && isExnessBaseKey(meta?.base_key);
  if (els.priceSourceWrap) {
    els.priceSourceWrap.hidden = venue === "EXNESS";
  }
  if (els.exnessBlock) {
    els.exnessBlock.hidden = !isExnessBaseKey(meta?.base_key);
  }
  if (els.spotBlock) {
    els.spotBlock.hidden = !isSpotBaseKey(meta?.base_key);
  }
  if (els.priceSource) {
    if (venue === "EXNESS") {
      els.priceSource.value = "exness";
      els.priceSource.disabled = true;
    } else {
      els.priceSource.disabled = !showExnessOption;
      if (!showExnessOption) els.priceSource.value = "chart";
    }
  }
}

async function refreshBrokerCompare() {
  const meta = currentMeta();
  const symbolId = currentSymbolId();
  if (!meta) return;

  if (els.spotBlock) {
    els.spotBlock.hidden = !isSpotBaseKey(meta.base_key);
  }
  if (!isExnessBaseKey(meta.base_key)) {
    if (els.exnessBlock) els.exnessBlock.hidden = true;
    if (!isSpotBaseKey(meta.base_key)) return;
  }

  try {
    const params = new URLSearchParams({
      instrument: meta.base_key,
      symbol_id: symbolId,
      _ts: String(Date.now()),
    });
    const res = await fetch(`/api/broker/compare?${params.toString()}`, { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();

    const spot = data.spot_reference || {};
    if (els.spotBlock && isSpotBaseKey(meta.base_key)) {
      els.spotBlock.hidden = false;
      if (els.quoteSpotSym) els.quoteSpotSym.textContent = spot.symbol || spot.label || "Spot";
      if (els.quoteSpotPrice && spot.price != null) {
        els.quoteSpotPrice.textContent = fmtPrice(+spot.price);
      }
      if (els.quoteSpotDiff && data.diff_chart_spot) {
        const d = +data.diff_chart_spot.amount;
        const sign = d > 0 ? "+" : "";
        els.quoteSpotDiff.textContent = `Chart ${sign}${d.toFixed(2)}`;
        els.quoteSpotDiff.classList.remove("up", "down", "estimated");
        els.quoteSpotDiff.classList.add(d > 0 ? "up" : d < 0 ? "down" : "flat");
      }
    }

    if (!isExnessBaseKey(meta.base_key)) return;

    if (els.exnessBlock) els.exnessBlock.hidden = false;
    const ex = data.exness || {};
    if (els.quoteExnessSym) els.quoteExnessSym.textContent = ex.symbol || "—";
    if (els.quoteExnessPrice && ex.mid != null) {
      els.quoteExnessPrice.textContent = fmtPrice(+ex.mid);
    }
    if (els.quoteDiff && data.diff_exness_spot) {
      const d = +data.diff_exness_spot.amount;
      const sign = d > 0 ? "+" : "";
      const est = ex.status === "estimated" ? " est." : "";
      els.quoteDiff.textContent = `vs Spot ${sign}${d.toFixed(2)}${est}`;
      els.quoteDiff.classList.remove("up", "down", "estimated");
      if (ex.status === "estimated") els.quoteDiff.classList.add("estimated");
      else els.quoteDiff.classList.add(d > 0 ? "up" : d < 0 ? "down" : "flat");
    }
    if (data.alignment_note && data.diff_chart_spot && Math.abs(+data.diff_chart_spot.amount) > 1) {
      els.caption.textContent = data.alignment_note.slice(0, 120);
    }
  } catch (_) {
    /* optional panel */
  }
}

function hasLiveFeed(symbolId) {
  const meta = symbolMeta(symbolId);
  return Boolean(meta?.live);
}

function showToast(message) {
  els.toast.hidden = false;
  els.toast.textContent = message;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    els.toast.hidden = true;
  }, 4200);
}

function toEpoch(time) {
  // Live klines send unix seconds; signal/Yahoo candles send ISO strings.
  if (typeof time === "number" && Number.isFinite(time)) {
    return time > 1e12 ? Math.floor(time / 1000) : Math.floor(time);
  }
  const ms = new Date(`${time}Z`).getTime();
  return Math.floor(ms / 1000);
}

function pricePrecision(candles) {
  const sample = candles?.[candles.length - 1]?.close ?? 100;
  if (sample >= 1000) return { precision: 2, minMove: 0.01 };
  if (sample >= 1) return { precision: 2, minMove: 0.01 };
  if (sample >= 0.01) return { precision: 4, minMove: 0.0001 };
  if (sample >= 0.0001) return { precision: 6, minMove: 0.000001 };
  return { precision: 8, minMove: 0.00000001 };
}

/** Normalize candles so Lightweight Charts never gets bad OHLC / duplicate times. */
function sanitizeBars(candles) {
  const byTime = new Map();
  for (const c of candles) {
    const time = toEpoch(c.time);
    if (!Number.isFinite(time) || time <= 0) continue;
    const open = +c.open;
    const high = +c.high;
    const low = +c.low;
    const close = +c.close;
    const volume = Math.max(0, +c.volume || 0);
    if (![open, high, low, close].every((n) => Number.isFinite(n) && n > 0)) continue;
    const hi = Math.max(open, close, high);
    const lo = Math.min(open, close, low);
    // Skip absurd spikes that would explode the Y-axis (bad ticks / feed glitches).
    const mid = (open + close) / 2;
    if (mid > 0 && (hi > mid * 3 || lo < mid * 0.33)) continue;
    byTime.set(time, { time, open, high: hi, low: lo, close, volume });
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

function destroyChart() {
  stopRealtime();
  if (chart) {
    try {
      chart.remove();
    } catch (_) {}
  }
  chart = null;
  candleSeries = null;
  volumeSeries = null;
  priceLines = [];
  lastBar = null;
  lastBarTime = 0;
  lastChartClose = 0;
}

function ensureChart() {
  if (chart) return;

  chart = LightweightCharts.createChart(els.chart, {
    autoSize: true,
    layout: {
      background: { type: "solid", color: "transparent" },
      textColor: "#4a4436",
      fontFamily: "DM Sans, sans-serif",
    },
    grid: {
      vertLines: { color: "rgba(60,45,15,0.07)" },
      horzLines: { color: "rgba(60,45,15,0.07)" },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: {
      borderColor: "rgba(60,45,15,0.15)",
      autoScale: true,
      scaleMargins: { top: 0.08, bottom: 0.22 },
    },
    timeScale: {
      borderColor: "rgba(60,45,15,0.15)",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 4,
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#3dba7a",
    downColor: "#e25b4c",
    borderUpColor: "#3dba7a",
    borderDownColor: "#e25b4c",
    wickUpColor: "#3dba7a",
    wickDownColor: "#e25b4c",
    lastValueVisible: true,
    priceLineVisible: true,
  });

  volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
    color: "rgba(212,168,75,0.35)",
    lastValueVisible: false,
    priceLineVisible: false,
  });
  chart.priceScale("vol").applyOptions({
    visible: false,
    autoScale: true,
    scaleMargins: { top: 0.82, bottom: 0 },
  });
}

function drawChart(candles, signal) {
  if (typeof LightweightCharts === "undefined") return;
  if (!candles?.length) return;

  ensureChart();

  const bars = sanitizeBars(candles);
  if (!bars.length) {
    els.caption.textContent = "No valid candles to chart";
    return;
  }

  const iv = INTERVAL_SECONDS[els.interval.value] || 900;
  // Keep the last bar on the interval boundary (live ticks attach here).
  const last = { ...bars[bars.length - 1] };
  last.time = Math.floor(last.time / iv) * iv;
  if (bars.length >= 2 && last.time < bars[bars.length - 2].time) {
    last.time = bars[bars.length - 2].time + iv;
  }
  bars[bars.length - 1] = last;

  candleSeries.applyOptions({
    priceFormat: { type: "price", ...pricePrecision(bars) },
  });
  candleSeries.setData(
    bars.map(({ time, open, high, low, close }) => ({ time, open, high, low, close }))
  );
  volumeSeries.setData(
    bars.map(({ time, open, close, volume }) => ({
      time,
      value: volume,
      color: close >= open ? "rgba(61,186,122,0.35)" : "rgba(226,91,76,0.35)",
    }))
  );

  lastBar = { time: last.time, open: last.open, high: last.high, low: last.low, close: last.close };
  lastBarTime = last.time;
  lastChartClose = last.close;

  // Force a clean autoscale around price (fixes wild -40k…140k axes).
  candleSeries.priceScale().applyOptions({
    autoScale: true,
    scaleMargins: { top: 0.08, bottom: 0.22 },
  });

  priceLines.forEach((line) => {
    try {
      candleSeries.removePriceLine(line);
    } catch (_) {}
  });
  priceLines = [];

  if (signal && signal.side !== "WAIT") {
    const guides = [
      { price: signal.take_profit, color: "#3dba7a", title: "TP" },
      { price: signal.entry, color: "#f0c56d", title: "ENTRY" },
      { price: signal.stop_loss, color: "#e25b4c", title: "SL" },
    ];
    const mid = last.close;
    guides.forEach((g) => {
      const p = +g.price;
      // Ignore guide lines that are absurdly far from price (bad cross-feed levels).
      if (!Number.isFinite(p) || p <= 0 || Math.abs(p - mid) / mid > 0.15) return;
      priceLines.push(
        candleSeries.createPriceLine({
          price: p,
          color: g.color,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: g.title,
        })
      );
    });
  }

  chart.timeScale().fitContent();
  fitNext = false;
}

function fmtPrice(p) {
  if (p >= 1000) return p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(2);
  if (p >= 0.01) return p.toFixed(4);
  if (p >= 0.0001) return p.toFixed(6);
  return p.toFixed(8);
}

function updateMarketQuote({ price, changePct, label } = {}) {
  const meta = currentMeta();
  if (els.quotePair) {
    els.quotePair.textContent = label || meta?.display || meta?.label || currentSymbolId();
  }
  if (price != null && Number.isFinite(+price) && els.quotePrice) {
    els.quotePrice.textContent = fmtPrice(+price);
  }
  if (changePct != null && Number.isFinite(+changePct) && els.quoteChange) {
    const pct = +changePct;
    const sign = pct > 0 ? "+" : "";
    els.quoteChange.textContent = `${sign}${pct.toFixed(2)}%`;
    els.quoteChange.classList.remove("up", "down", "flat");
    els.quoteChange.classList.add(pct > 0 ? "up" : pct < 0 ? "down" : "flat");
  }
}

function applyTick(price, changePct) {
  if (Number.isFinite(price) && price > 0) {
    updateMarketQuote({ price, changePct });
  }
  if (!candleSeries || !lastBar || !Number.isFinite(price) || price <= 0) return;

  // Reject wild ticks that would blow up the Y-axis.
  if (lastChartClose > 0 && Math.abs(price - lastChartClose) / lastChartClose > 0.05) {
    return;
  }

  const iv = INTERVAL_SECONDS[els.interval.value] || 900;
  const nowSec = Math.floor(Date.now() / 1000);
  const barTime = Math.floor(nowSec / iv) * iv;

  if (barTime > lastBarTime) {
    // New candle period — also add a zero volume placeholder so scales stay aligned.
    lastBar = { time: barTime, open: price, high: price, low: price, close: price };
    lastBarTime = barTime;
    try {
      volumeSeries.update({
        time: barTime,
        value: 0,
        color: "rgba(212,168,75,0.25)",
      });
    } catch (_) {}
  } else {
    // Same (or clock-skewed earlier) period: tick the forming candle in place.
    lastBar.close = price;
    lastBar.high = Math.max(lastBar.high, price);
    lastBar.low = Math.min(lastBar.low, price);
  }

  try {
    candleSeries.update({
      time: lastBar.time,
      open: lastBar.open,
      high: lastBar.high,
      low: lastBar.low,
      close: lastBar.close,
    });
  } catch (_) {
    // If update fails (duplicate/out-of-order), skip this tick.
    return;
  }
  lastChartClose = price;

  const now = Date.now();
  if (now - lastUiTickMs >= 80) {
    lastUiTickMs = now;
    const sym = lastSignal?.symbol || currentMeta()?.label || currentSymbolId();
    const src = liveSource ? ` · ${liveSource}` : "";
    els.caption.textContent = `${sym} · ${fmtPrice(price)} · live${src}`;
    if (els.live) els.live.textContent = `Live · ${fmtPrice(price)}`;
  }
}

function stopRealtime() {
  if (tickerTimer) {
    clearInterval(tickerTimer);
    tickerTimer = null;
  }
}

function startRealtime() {
  const symbolId = currentSymbolId();
  if (!hasLiveFeed(symbolId)) {
    stopRealtime();
    const meta = currentMeta();
    els.caption.textContent = `${meta?.display || symbolId} · click Analyze for chart`;
    return;
  }

  stopRealtime();
  const tickOnce = async () => {
    try {
      const res = await fetch(
        `/api/live/ticker?symbol_id=${encodeURIComponent(symbolId)}&_ts=${Date.now()}`,
        { cache: "no-store" }
      );
      if (!res.ok) return;
      const data = await res.json();
      liveSource = data.source || data.venue?.toLowerCase() || "binance";
      applyTick(+data.price, data.change_pct != null ? +data.change_pct : undefined);
    } catch (_) {
      /* keep last price; next tick retries */
    }
  };

  tickOnce();
  tickerTimer = setInterval(() => {
    tickOnce();
    refreshBrokerCompare();
  }, 200);
  refreshBrokerCompare();
}

/** Seed the chart from Binance candles, then stream live ticks. */
async function loadChartSeed() {
  const symbolId = currentSymbolId();
  const interval = els.interval.value;
  const meta = currentMeta();

  if (!hasLiveFeed(symbolId)) {
    destroyChart();
    els.caption.textContent = `${meta?.display || symbolId} · click Analyze to load chart`;
    return;
  }

  els.caption.textContent = `${meta?.display || symbolId} · loading chart…`;
  try {
    const res = await fetch(
      `/api/live/klines?symbol_id=${encodeURIComponent(symbolId)}` +
        `&interval=${encodeURIComponent(interval)}&limit=80&_ts=${Date.now()}`,
      { cache: "no-store" }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Live klines ${res.status}`);
    }
    const data = await res.json();
    destroyChart();
    drawChart(data.candles, lastSignal && lastSignal.side !== "WAIT" ? lastSignal : null);
    startRealtime();
  } catch (err) {
    console.error(err);
    els.caption.textContent = `${meta?.display || symbolId} · chart unavailable — ${err.message}`;
    showToast(err.message || "Chart unavailable");
  }
}

function renderSignal(data) {
  lastSignal = data;
  els.board.hidden = false;
  els.detail.hidden = false;

  els.core.classList.remove("buy", "sell", "wait");
  const sideClass = data.side === "BUY" ? "buy" : data.side === "SELL" ? "sell" : "wait";
  els.core.classList.add(sideClass);

  els.side.textContent = data.side;
  els.entry.textContent = Number(data.entry).toFixed(2);
  els.timeframe.textContent = `${data.symbol} · ${data.timeframe} · ${data.analysis_mode || "indicators"}`;
  els.votesTitle.textContent =
    data.analysis_mode === "candles" ? "Pattern votes" : "Indicator votes";
  els.lot.textContent = data.side === "WAIT" ? "0.00" : Number(data.lot_size).toFixed(2);
  els.sl.textContent = Number(data.stop_loss).toFixed(2);
  els.tp.textContent = Number(data.take_profit).toFixed(2);
  els.win.textContent = `${Number(data.win_probability).toFixed(1)}%`;
  els.conf.textContent = `Confidence ${Number(data.confidence).toFixed(1)}%`;
  els.slNote.textContent = `Distance $${Number(data.sl_distance).toFixed(2)} · ATR-based`;
  els.rr.textContent = `Distance $${Number(data.tp_distance).toFixed(2)} · R:R ${Number(data.risk_reward).toFixed(2)}`;
  els.riskNote.textContent =
    data.side === "WAIT"
      ? "No trade — wait for confluence"
      : `Risk ≈ $${Number(data.risk_amount).toFixed(2)} on $${Number(data.account_balance).toFixed(0)}`;

  els.reasons.innerHTML = "";
  (data.reasons || []).forEach((reason) => {
    const li = document.createElement("li");
    li.textContent = reason;
    els.reasons.appendChild(li);
  });

  els.votes.innerHTML = "";
  (data.indicator_votes || []).forEach((vote) => {
    const row = document.createElement("div");
    row.className = "vote";
    row.innerHTML = `
      <strong>${vote.name}</strong>
      <span class="side ${vote.side}">${vote.side}</span>
      <p>${vote.reason}</p>
    `;
    els.votes.appendChild(row);
  });

  els.snap.innerHTML = "";
  const snap = data.snapshot || {};
  Object.entries(snap).forEach(([key, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = key.replaceAll("_", " ");
    const dd = document.createElement("dd");
    dd.textContent = value;
    els.snap.appendChild(dt);
    els.snap.appendChild(dd);
  });

  if (data.recent_edge?.forward_hit_rate_pct != null) {
    els.edge.textContent = `Recent sample edge: ${data.recent_edge.forward_hit_rate_pct}% hit rate across ${data.recent_edge.sample_signals} similar signals (forward ATR probe — not a guarantee).`;
  } else {
    els.edge.textContent = "Recent sample edge unavailable for this window.";
  }

  els.disclaimer.textContent = data.disclaimer;
  els.live.textContent = data.side === "WAIT" ? "Stand by" : "Signal ready";

  if (data.broker_compare?.exness) {
    refreshBrokerCompare();
  }

  // Keep the live Binance chart moving — only overlay TP/SL/ENTRY lines.
  // Do NOT replace the live seed with slow Yahoo candles (that caused the delay).
  if (candleSeries && lastBar) {
    priceLines.forEach((line) => {
      try {
        candleSeries.removePriceLine(line);
      } catch (_) {}
    });
    priceLines = [];
    if (data.side !== "WAIT") {
      const guides = [
        { price: data.take_profit, color: "#3dba7a", title: "TP" },
        { price: data.entry, color: "#f0c56d", title: "ENTRY" },
        { price: data.stop_loss, color: "#e25b4c", title: "SL" },
      ];
      guides.forEach((g) => {
        priceLines.push(
          candleSeries.createPriceLine({
            price: g.price,
            color: g.color,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: g.title,
          })
        );
      });
    }
  } else {
    drawChart(data.candles, data);
    startRealtime();
  }
}

async function analyze() {
  if (fetching) return;
  fetching = true;

  const interval = els.interval.value;
  const symbolId = currentSymbolId();
  const mode = els.mode.value;
  const price_source = els.priceSource?.value || "chart";
  const account_balance = Number(els.balance.value) || 1000;
  const risk_percent = Number(els.risk.value) || 2;

  els.btn.disabled = true;
  els.btn.textContent = "Reading chart…";
  els.live.textContent = "Analyzing";

  try {
    const params = new URLSearchParams({
      interval,
      symbol_id: symbolId,
      mode,
      price_source,
      account_balance: String(account_balance),
      risk_percent: String(risk_percent),
      _ts: String(Date.now()),
    });
    const res = await fetch(`/api/signal?${params.toString()}`, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Signal request failed");
    }
    renderSignal(data);
    refreshBrokerCompare();
  } catch (err) {
    console.error(err);
    showToast(err.message || "Could not fetch signal");
    els.live.textContent = "Error";
  } finally {
    fetching = false;
    els.btn.disabled = false;
    els.btn.textContent = "Analyze chart";
  }
}

function filteredSymbols() {
  const q = symbolFilter.trim().toLowerCase();
  if (!q) {
    const pinned = POPULAR_SYMBOL_IDS.map((id) => symbolMeta(id)).filter(Boolean);
    const rest = symbolCatalog.filter((s) => !POPULAR_SYMBOL_IDS.includes(s.id)).slice(0, 53);
    return [...pinned, ...rest];
  }
  const terms = q.split(/\s+/).filter(Boolean);
  return symbolCatalog
    .filter((s) => {
      const hay = `${s.id} ${s.venue} ${s.symbol} ${s.label} ${s.name} ${s.keywords || ""} ${s.display || ""}`.toLowerCase();
      return terms.every((term) => hay.includes(term));
    })
    .sort((a, b) => {
      const goldish = terms.some((t) => ["gold", "xau", "xauusd"].includes(t));
      if (!goldish) return 0;
      if (a.id === "EXNESS:XAUUSDm") return -1;
      if (b.id === "EXNESS:XAUUSDm") return 1;
      if (a.venue === "EXNESS" && a.base_key === "XAUUSD") return -1;
      if (b.venue === "EXNESS" && b.base_key === "XAUUSD") return 1;
      return 0;
    })
    .slice(0, 80);
}

async function fetchSymbolSearch(query) {
  const q = (query || "").trim();
  const url = q
    ? `/api/symbols?q=${encodeURIComponent(q)}&_ts=${Date.now()}`
    : `/api/symbols?_ts=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error("Symbol search failed");
  const data = await res.json();
  symbolCatalog = data.symbols || [];
  return symbolCatalog;
}

function renderSymbolList() {
  const rows = filteredSymbols();
  if (!els.instrumentList) return;
  if (!rows.length) {
    els.instrumentList.innerHTML = `<li class="empty">No symbols match “${symbolFilter}”</li>`;
    els.instrumentList.hidden = false;
    highlightIndex = -1;
    return;
  }
  els.instrumentList.innerHTML = rows
    .map((s, idx) => {
      const live = s.live ? "Live" : "Delayed";
      const active = idx === highlightIndex ? "active" : "";
      return `<li class="${active}" data-id="${s.id}" role="option">
        <span class="pair">${venueBadge(s.venue)}${s.label}</span>
        <span class="meta">${s.name} · ${live}</span>
      </li>`;
    })
    .join("");
  els.instrumentList.hidden = false;
}

function selectSymbol(id, { reload = true } = {}) {
  const meta = symbolMeta(id) || { id, label: id, name: id, display: id, venue: "BINANCE" };
  els.symbolId.value = meta.id;
  if (els.instrumentSearch) {
    els.instrumentSearch.value = `${meta.venue} · ${meta.label} — ${meta.name}`;
  }
  if (els.instrumentList) els.instrumentList.hidden = true;
  highlightIndex = -1;
  updateMarketQuote({ label: meta.display || `${meta.venue} · ${meta.label}` });
  if (els.quotePrice) els.quotePrice.textContent = "—";
  if (els.quoteChange) {
    els.quoteChange.textContent = "—";
    els.quoteChange.classList.remove("up", "down");
    els.quoteChange.classList.add("flat");
  }
  if (reload) {
    fitNext = true;
    lastSignal = null;
    els.board.hidden = true;
    els.detail.hidden = true;
    syncPriceSourceUi();
    loadChartSeed();
    refreshBrokerCompare();
  } else {
    syncPriceSourceUi();
  }
}

async function loadSymbolCatalog() {
  await fetchSymbolSearch("");
  const initial =
    symbolCatalog.find((s) => s.id === "BINANCE:BTCUSDT") ||
    symbolCatalog.find((s) => s.id === "EXNESS:XAUUSDm") ||
    symbolCatalog[0];
  if (initial) selectSymbol(initial.id, { reload: false });
}

function scheduleSymbolSearch(query) {
  clearTimeout(symbolSearchTimer);
  symbolSearchTimer = setTimeout(async () => {
    try {
      await fetchSymbolSearch(query);
      renderSymbolList();
    } catch (err) {
      console.error(err);
    }
  }, query ? 180 : 0);
}

function wireInstrumentSearch() {
  if (!els.instrumentSearch || !els.instrumentList) return;

  els.instrumentSearch.addEventListener("focus", () => {
    symbolFilter = "";
    highlightIndex = 0;
    scheduleSymbolSearch("");
    renderSymbolList();
    els.instrumentSearch.select();
  });

  els.instrumentSearch.addEventListener("input", () => {
    symbolFilter = els.instrumentSearch.value;
    highlightIndex = 0;
    scheduleSymbolSearch(symbolFilter);
    renderSymbolList();
  });

  els.instrumentSearch.addEventListener("keydown", (e) => {
    const rows = filteredSymbols();
    if (e.key === "ArrowDown") {
      e.preventDefault();
      highlightIndex = Math.min(highlightIndex + 1, rows.length - 1);
      renderSymbolList();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlightIndex = Math.max(highlightIndex - 1, 0);
      renderSymbolList();
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = rows[Math.max(0, highlightIndex)];
      if (pick) selectSymbol(pick.id);
    } else if (e.key === "Escape") {
      els.instrumentList.hidden = true;
    }
  });

  els.instrumentList.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-id]");
    if (!li) return;
    e.preventDefault();
    selectSymbol(li.dataset.id);
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#instrumentPicker")) {
      els.instrumentList.hidden = true;
    }
  });
}

els.btn.addEventListener("click", () => analyze());

els.mode.addEventListener("change", () => {
  // Mode only affects the next Analyze click — chart keeps streaming.
});

els.interval.addEventListener("change", () => {
  fitNext = true;
  loadChartSeed();
});

wireInstrumentSearch();
loadSymbolCatalog()
  .then(() => loadChartSeed())
  .catch((err) => {
    console.error(err);
    showToast("Could not load symbol list");
    loadChartSeed();
  });
