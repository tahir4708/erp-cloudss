const $ = (id) => document.getElementById(id);

const els = {
  btn: $("analyzeBtn"),
  interval: $("interval"),
  balance: $("balance"),
  risk: $("risk"),
  live: $("liveStatus"),
  board: $("signalBoard"),
  detail: $("detailGrid"),
  side: $("sideValue"),
  entry: $("entryValue"),
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
  snap: $("snapList"),
  edge: $("edgeNote"),
  disclaimer: $("disclaimer"),
  caption: $("chartCaption"),
  toast: $("toast"),
  core: $("signalCore"),
  canvas: $("priceChart"),
};

let lastSignal = null;

function showToast(message) {
  els.toast.hidden = false;
  els.toast.textContent = message;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    els.toast.hidden = true;
  }, 4200);
}

function drawChart(candles, signal) {
  const canvas = els.canvas;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 900;
  const cssH = 420;
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  if (!candles?.length) return;

  const pad = { top: 24, right: 18, bottom: 28, left: 18 };
  const w = cssW - pad.left - pad.right;
  const h = cssH - pad.top - pad.bottom;

  let min = Math.min(...candles.map((c) => c.low));
  let max = Math.max(...candles.map((c) => c.high));
  if (signal) {
    min = Math.min(min, signal.stop_loss, signal.take_profit, signal.entry);
    max = Math.max(max, signal.stop_loss, signal.take_profit, signal.entry);
  }
  const span = Math.max(max - min, 1);
  min -= span * 0.04;
  max += span * 0.04;

  const xAt = (i) => pad.left + (i / Math.max(candles.length - 1, 1)) * w;
  const yAt = (price) => pad.top + ((max - price) / (max - min)) * h;

  ctx.strokeStyle = "rgba(212,168,75,0.12)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = pad.top + (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + w, y);
    ctx.stroke();
  }

  if (signal && signal.side !== "WAIT") {
    const guides = [
      { price: signal.take_profit, color: "rgba(61,186,122,0.85)", label: "TP" },
      { price: signal.entry, color: "rgba(240,197,109,0.9)", label: "ENTRY" },
      { price: signal.stop_loss, color: "rgba(226,91,76,0.85)", label: "SL" },
    ];
    guides.forEach((g) => {
      const y = yAt(g.price);
      ctx.strokeStyle = g.color;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + w, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = g.color;
      ctx.font = "600 11px DM Sans, sans-serif";
      ctx.fillText(`${g.label} ${g.price.toFixed(2)}`, pad.left + 6, y - 6);
    });
  }

  const candleW = Math.max(2, (w / candles.length) * 0.55);
  candles.forEach((c, i) => {
    const x = xAt(i);
    const bull = c.close >= c.open;
    ctx.strokeStyle = bull ? "#3dba7a" : "#e25b4c";
    ctx.fillStyle = bull ? "rgba(61,186,122,0.85)" : "rgba(226,91,76,0.85)";

    ctx.beginPath();
    ctx.moveTo(x, yAt(c.high));
    ctx.lineTo(x, yAt(c.low));
    ctx.stroke();

    const y1 = yAt(Math.max(c.open, c.close));
    const y2 = yAt(Math.min(c.open, c.close));
    ctx.fillRect(x - candleW / 2, y1, candleW, Math.max(y2 - y1, 1));
  });

  ctx.beginPath();
  candles.forEach((c, i) => {
    const x = xAt(i);
    const y = yAt(c.close);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = "rgba(240,197,109,0.55)";
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

function renderSignal(data) {
  lastSignal = data;
  els.board.hidden = false;
  els.detail.hidden = false;

  els.core.classList.remove("buy", "sell", "wait");
  const sideClass = data.side === "BUY" ? "buy" : data.side === "SELL" ? "sell" : "wait";
  els.core.classList.add(sideClass);

  els.side.textContent = data.side;
  els.entry.textContent = `Entry ${Number(data.entry).toFixed(2)} · ${data.timeframe}`;
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
  els.caption.textContent = `${data.symbol} · last ${data.candles?.length || 0} candles · ATR ${Number(data.atr).toFixed(2)}`;
  els.live.textContent = data.side === "WAIT" ? "Stand by" : "Signal live";

  drawChart(data.candles, data);
}

async function analyze() {
  const interval = els.interval.value;
  const account_balance = Number(els.balance.value) || 1000;
  const risk_percent = Number(els.risk.value) || 2;

  els.btn.disabled = true;
  els.btn.textContent = "Reading chart…";
  els.live.textContent = "Analyzing";

  try {
    const params = new URLSearchParams({
      interval,
      account_balance: String(account_balance),
      risk_percent: String(risk_percent),
    });
    const res = await fetch(`/api/signal?${params.toString()}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Signal request failed");
    }
    renderSignal(data);
  } catch (err) {
    console.error(err);
    showToast(err.message || "Could not fetch signal");
    els.live.textContent = "Error";
  } finally {
    els.btn.disabled = false;
    els.btn.textContent = "Analyze chart";
  }
}

els.btn.addEventListener("click", analyze);
window.addEventListener("resize", () => {
  if (lastSignal) drawChart(lastSignal.candles, lastSignal);
});

analyze();
