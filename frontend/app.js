const $ = (id) => document.getElementById(id);

const els = {
  btn: $("analyzeBtn"),
  instrument: $("instrument"),
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
  liveToggle: $("liveToggle"),
  refreshRate: $("refreshRate"),
};

let lastSignal = null;
let liveTimer = null;
let countdownTimer = null;
let fetching = false;

let chart = null;
let candleSeries = null;
let volumeSeries = null;
let priceLines = [];
let fitNext = true;

// Real-time tick feed (free, no API key) via Binance WebSocket.
//  - BTCUSD -> btcusdt (spot crypto)
//  - XAUUSD -> paxgusdt (PAX Gold ≈ spot gold; basis-aligned to the chart)
// USOIL has no free per-second websocket, so it stays on the polling refresh.
const BINANCE_SYMBOLS = { BTCUSD: "btcusdt", XAUUSD: "paxgusdt" };
const BINANCE_INTERVALS = {
  "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
  "1h": "1h", "4h": "4h", "1d": "1d",
};
let ws = null;
let wsKey = null;
let lastBarTime = 0;
let lastChartClose = 0;
let lastBar = null; // OHLC of the forming candle, updated live tick-by-tick
let feedBasis = null; // offset added to raw feed prices to align with the chart

function showToast(message) {
  els.toast.hidden = false;
  els.toast.textContent = message;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    els.toast.hidden = true;
  }, 4200);
}

function toEpoch(iso) {
  // Backend sends tz-naive UTC timestamps; treat them as UTC.
  const ms = new Date(`${iso}Z`).getTime();
  return Math.floor(ms / 1000);
}

function pricePrecision(candles) {
  const sample = candles?.[candles.length - 1]?.close ?? 100;
  if (sample >= 1000) return { precision: 2, minMove: 0.01 };
  if (sample >= 1) return { precision: 2, minMove: 0.01 };
  return { precision: 4, minMove: 0.0001 };
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
    rightPriceScale: { borderColor: "rgba(60,45,15,0.15)" },
    timeScale: {
      borderColor: "rgba(60,45,15,0.15)",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#3dba7a",
    downColor: "#e25b4c",
    borderUpColor: "#3dba7a",
    borderDownColor: "#e25b4c",
    wickUpColor: "#3dba7a",
    wickDownColor: "#e25b4c",
  });

  volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
    color: "rgba(212,168,75,0.35)",
  });
  chart.priceScale("vol").applyOptions({
    scaleMargins: { top: 0.82, bottom: 0 },
  });
}

function drawChart(candles, signal) {
  if (typeof LightweightCharts === "undefined") return;
  if (!candles?.length) return;

  ensureChart();

  candleSeries.applyOptions({ priceFormat: { type: "price", ...pricePrecision(candles) } });

  const bars = candles.map((c) => ({
    time: toEpoch(c.time),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
  candleSeries.setData(bars);
  lastBarTime = bars.length ? bars[bars.length - 1].time : 0;
  lastChartClose = bars.length ? bars[bars.length - 1].close : 0;
  lastBar = bars.length ? { ...bars[bars.length - 1] } : null;
  // Re-anchor the live feed to this freshly polled close so the tick stream
  // realigns each refresh instead of drifting away from the chart.
  feedBasis = null;

  volumeSeries.setData(
    candles.map((c) => ({
      time: toEpoch(c.time),
      value: c.volume || 0,
      color: c.close >= c.open ? "rgba(61,186,122,0.35)" : "rgba(226,91,76,0.35)",
    }))
  );

  priceLines.forEach((line) => candleSeries.removePriceLine(line));
  priceLines = [];

  if (signal && signal.side !== "WAIT") {
    const guides = [
      { price: signal.take_profit, color: "#3dba7a", title: "TP" },
      { price: signal.entry, color: "#f0c56d", title: "ENTRY" },
      { price: signal.stop_loss, color: "#e25b4c", title: "SL" },
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

  if (fitNext) {
    chart.timeScale().fitContent();
    fitNext = false;
  }
}

function fmtPrice(p) {
  if (p >= 1000) return p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(2);
  return p.toFixed(4);
}

function stopRealtime() {
  if (ws) {
    try {
      ws.onclose = null;
      ws.close();
    } catch (_) {}
  }
  ws = null;
  wsKey = null;
}

function connectRealtime() {
  const instrument = els.instrument.value;
  const interval = els.interval.value;
  const symbol = BINANCE_SYMBOLS[instrument];
  const binInterval = BINANCE_INTERVALS[interval];

  // No free per-second feed for this instrument/timeframe → polling only.
  if (!symbol || !binInterval) {
    stopRealtime();
    return;
  }

  const desiredKey = `${symbol}@${binInterval}`;
  if (desiredKey === wsKey && ws && ws.readyState <= 1) return; // already connected

  stopRealtime();
  wsKey = desiredKey;
  feedBasis = null; // recomputed on first tick to align feed with the chart

  const url = `wss://stream.binance.com:9443/ws/${symbol}@kline_${binInterval}`;
  let socket;
  try {
    socket = new WebSocket(url);
  } catch (_) {
    return;
  }
  ws = socket;

  socket.onmessage = (event) => {
    if (socket !== ws || !candleSeries || !lastBar) return;
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    const k = msg.k;
    if (!k) return;

    // Align the feed to the chart's price scale (e.g. PAX Gold spot vs gold
    // futures, or Binance vs Yahoo). Basis is fixed once at first tick so the
    // first live price matches the chart's last close, then fluctuates from
    // there. Recomputed whenever a fresh poll resets the chart data.
    if (feedBasis === null) {
      feedBasis = lastChartClose ? lastChartClose - +k.c : 0;
    }

    const price = +k.c + feedBasis;
    const barTime = Math.floor(k.t / 1000);

    if (barTime > lastBarTime) {
      // A brand-new candle period opened on the live feed: append it so the
      // chart rolls forward instead of overwriting the previous bar.
      lastBar = {
        time: barTime,
        open: +k.o + feedBasis,
        high: +k.h + feedBasis,
        low: +k.l + feedBasis,
        close: price,
      };
      lastBarTime = barTime;
    } else {
      // Same (or earlier-stamped) period: tick the forming candle in place.
      // Yahoo stamps the partial bar at the fetch instant, so the Binance
      // bar-open time is usually *earlier* — we pin the update to the chart's
      // own last-bar time and just move close / extend the wicks.
      lastBar.close = price;
      lastBar.high = Math.max(lastBar.high, price);
      lastBar.low = Math.min(lastBar.low, price);
    }

    candleSeries.update({
      time: lastBar.time,
      open: lastBar.open,
      high: lastBar.high,
      low: lastBar.low,
      close: lastBar.close,
    });
    lastChartClose = price;

    els.caption.textContent = `${lastSignal?.symbol || els.instrument.value} · ${fmtPrice(price)} · live`;
  };

  socket.onclose = () => {
    // Reconnect if this feed is still the desired one.
    if (socket === ws) {
      ws = null;
      setTimeout(() => {
        if (wsKey === desiredKey) connectRealtime();
      }, 2000);
    }
  };
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
  const stamp = new Date().toLocaleTimeString();
  const liveTag = els.liveToggle?.checked ? ` · live · updated ${stamp}` : "";
  els.caption.textContent = `${data.symbol} · last ${data.candles?.length || 0} candles · ATR ${Number(data.atr).toFixed(2)}${liveTag}`;
  els.live.textContent = data.side === "WAIT" ? "Stand by" : "Signal live";

  drawChart(data.candles, data);
  connectRealtime();
}

async function analyze({ silent = false } = {}) {
  // Prevent overlapping requests from stacking (matters at 1s refresh).
  if (fetching) return;
  fetching = true;

  const interval = els.interval.value;
  const instrument = els.instrument.value;
  const mode = els.mode.value;
  const account_balance = Number(els.balance.value) || 1000;
  const risk_percent = Number(els.risk.value) || 2;

  if (!silent) {
    els.btn.disabled = true;
    els.btn.textContent = "Reading chart…";
    els.live.textContent = "Analyzing";
  }

  try {
    const params = new URLSearchParams({
      interval,
      instrument,
      mode,
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
  } catch (err) {
    console.error(err);
    if (!silent) showToast(err.message || "Could not fetch signal");
    els.live.textContent = silent ? "Live · retrying" : "Error";
  } finally {
    fetching = false;
    if (!silent) {
      els.btn.disabled = false;
      els.btn.textContent = "Analyze chart";
    }
  }
}

function stopLive() {
  clearInterval(liveTimer);
  clearInterval(countdownTimer);
  liveTimer = null;
  countdownTimer = null;
}

function startLive() {
  stopLive();
  const seconds = Number(els.refreshRate.value) || 30;
  let remaining = seconds;

  countdownTimer = setInterval(() => {
    remaining -= 1;
    if (remaining >= 0 && els.liveToggle.checked) {
      els.live.textContent = `Live · next ${remaining}s`;
    }
  }, 1000);

  liveTimer = setInterval(async () => {
    await analyze({ silent: true });
    remaining = Number(els.refreshRate.value) || 30;
  }, seconds * 1000);

  analyze({ silent: true });
}

els.btn.addEventListener("click", () => analyze());

els.liveToggle.addEventListener("change", () => {
  if (els.liveToggle.checked) startLive();
  else {
    stopLive();
    els.live.textContent = lastSignal?.side === "WAIT" ? "Stand by" : "Signal live";
  }
});

els.refreshRate.addEventListener("change", () => {
  if (els.liveToggle.checked) startLive();
});

els.instrument.addEventListener("change", () => {
  fitNext = true;
  if (els.liveToggle.checked) startLive();
  else analyze();
});

els.mode.addEventListener("change", () => {
  fitNext = true;
  if (els.liveToggle.checked) startLive();
  else analyze();
});

els.interval.addEventListener("change", () => {
  fitNext = true;
  if (els.liveToggle.checked) startLive();
  else analyze();
});

analyze();
