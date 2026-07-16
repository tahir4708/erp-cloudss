"""Signal engine: confluence-based Buy/Sell with lot size, TP/SL, win %."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from backend.config import settings
from backend.data_feed import candles_to_list, fetch_ohlcv
from backend.indicators import enrich, latest_snapshot, safe_nan

Side = Literal["BUY", "SELL", "WAIT"]


@dataclass
class Vote:
    name: str
    side: Literal["BUY", "SELL", "NEUTRAL"]
    weight: float
    reason: str


@dataclass
class TradeSignal:
    symbol: str
    side: Side
    lot_size: float
    entry: float
    stop_loss: float
    take_profit: float
    sl_distance: float
    tp_distance: float
    win_probability: float
    confidence: float
    risk_reward: float
    atr: float
    timeframe: str
    reasons: list[str] = field(default_factory=list)
    indicator_votes: list[dict[str, Any]] = field(default_factory=list)
    account_balance: float = 1000.0
    risk_amount: float = 0.0
    disclaimer: str = (
        "Educational signals only — not financial advice. "
        "No signal is 100% accurate. Always manage your own risk."
    )
    candles: list[dict[str, Any]] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _votes(snap: dict) -> list[Vote]:
    votes: list[Vote] = []
    price = snap["price"]

    # 1) EMA trend stack
    if snap["ema_fast"] > snap["ema_slow"] > snap["ema_trend"]:
        votes.append(Vote("EMA Trend", "BUY", 1.2, "Fast > Slow > Trend EMA (bullish stack)"))
    elif snap["ema_fast"] < snap["ema_slow"] < snap["ema_trend"]:
        votes.append(Vote("EMA Trend", "SELL", 1.2, "Fast < Slow < Trend EMA (bearish stack)"))
    else:
        votes.append(Vote("EMA Trend", "NEUTRAL", 0.4, "EMAs mixed — no clear trend stack"))

    # 2) EMA crossover momentum
    crossed_up = snap["ema_fast_prev"] <= snap["ema_slow_prev"] and snap["ema_fast"] > snap["ema_slow"]
    crossed_dn = snap["ema_fast_prev"] >= snap["ema_slow_prev"] and snap["ema_fast"] < snap["ema_slow"]
    if crossed_up:
        votes.append(Vote("EMA Cross", "BUY", 1.0, "Bullish EMA 9/21 crossover"))
    elif crossed_dn:
        votes.append(Vote("EMA Cross", "SELL", 1.0, "Bearish EMA 9/21 crossover"))
    elif snap["ema_fast"] > snap["ema_slow"]:
        votes.append(Vote("EMA Cross", "BUY", 0.5, "Price structure still above slow EMA"))
    elif snap["ema_fast"] < snap["ema_slow"]:
        votes.append(Vote("EMA Cross", "SELL", 0.5, "Price structure still below slow EMA"))
    else:
        votes.append(Vote("EMA Cross", "NEUTRAL", 0.3, "No EMA edge"))

    # 3) MACD
    if snap["macd_hist"] > 0 and snap["macd_hist"] > snap["macd_hist_prev"]:
        votes.append(Vote("MACD", "BUY", 1.1, "MACD histogram rising above zero"))
    elif snap["macd_hist"] < 0 and snap["macd_hist"] < snap["macd_hist_prev"]:
        votes.append(Vote("MACD", "SELL", 1.1, "MACD histogram falling below zero"))
    elif snap["macd"] > snap["macd_signal"]:
        votes.append(Vote("MACD", "BUY", 0.6, "MACD line above signal"))
    elif snap["macd"] < snap["macd_signal"]:
        votes.append(Vote("MACD", "SELL", 0.6, "MACD line below signal"))
    else:
        votes.append(Vote("MACD", "NEUTRAL", 0.3, "MACD flat"))

    # 4) RSI
    rsi = snap["rsi"]
    if 45 <= rsi <= 65 and price > snap["ema_trend"]:
        votes.append(Vote("RSI", "BUY", 0.9, f"RSI {rsi:.1f} in bullish momentum zone"))
    elif 35 <= rsi <= 55 and price < snap["ema_trend"]:
        votes.append(Vote("RSI", "SELL", 0.9, f"RSI {rsi:.1f} in bearish momentum zone"))
    elif rsi < 30:
        votes.append(Vote("RSI", "BUY", 0.8, f"RSI {rsi:.1f} oversold — bounce bias"))
    elif rsi > 70:
        votes.append(Vote("RSI", "SELL", 0.8, f"RSI {rsi:.1f} overbought — pullback bias"))
    else:
        votes.append(Vote("RSI", "NEUTRAL", 0.3, f"RSI {rsi:.1f} neutral"))

    # 5) Stochastic
    if snap["stoch_k"] < 25 and snap["stoch_k"] > snap["stoch_d"]:
        votes.append(Vote("Stochastic", "BUY", 0.8, "Stoch turning up from oversold"))
    elif snap["stoch_k"] > 75 and snap["stoch_k"] < snap["stoch_d"]:
        votes.append(Vote("Stochastic", "SELL", 0.8, "Stoch turning down from overbought"))
    elif snap["stoch_k"] > snap["stoch_d"]:
        votes.append(Vote("Stochastic", "BUY", 0.4, "Stoch %K above %D"))
    elif snap["stoch_k"] < snap["stoch_d"]:
        votes.append(Vote("Stochastic", "SELL", 0.4, "Stoch %K below %D"))
    else:
        votes.append(Vote("Stochastic", "NEUTRAL", 0.2, "Stochastic neutral"))

    # 6) Bollinger
    bb_pct = snap["bb_pct"]
    if bb_pct <= 0.15:
        votes.append(Vote("Bollinger", "BUY", 0.9, "Price near lower Bollinger band"))
    elif bb_pct >= 0.85:
        votes.append(Vote("Bollinger", "SELL", 0.9, "Price near upper Bollinger band"))
    elif price > snap["bb_mid"]:
        votes.append(Vote("Bollinger", "BUY", 0.35, "Price above BB mid"))
    elif price < snap["bb_mid"]:
        votes.append(Vote("Bollinger", "SELL", 0.35, "Price below BB mid"))
    else:
        votes.append(Vote("Bollinger", "NEUTRAL", 0.2, "Inside Bollinger mid"))

    # 7) ADX trend strength + direction
    adx = snap["adx"]
    if adx >= 20:
        if snap["adx_pos"] > snap["adx_neg"]:
            votes.append(Vote("ADX", "BUY", 1.0, f"ADX {adx:.1f} with +DI leading (trend up)"))
        elif snap["adx_neg"] > snap["adx_pos"]:
            votes.append(Vote("ADX", "SELL", 1.0, f"ADX {adx:.1f} with -DI leading (trend down)"))
        else:
            votes.append(Vote("ADX", "NEUTRAL", 0.3, f"ADX {adx:.1f} direction unclear"))
    else:
        votes.append(Vote("ADX", "NEUTRAL", 0.4, f"ADX {adx:.1f} — weak trend, choppy"))

    # 8) Price vs swing structure
    mid_range = (snap["swing_high"] + snap["swing_low"]) / 2
    if price > mid_range and price > snap["ema_trend"]:
        votes.append(Vote("Structure", "BUY", 0.7, "Holding upper half of recent range"))
    elif price < mid_range and price < snap["ema_trend"]:
        votes.append(Vote("Structure", "SELL", 0.7, "Holding lower half of recent range"))
    else:
        votes.append(Vote("Structure", "NEUTRAL", 0.3, "Price mid-range / mixed structure"))

    return votes


def _score(votes: list[Vote]) -> tuple[Side, float, float, list[str]]:
    buy = sum(v.weight for v in votes if v.side == "BUY")
    sell = sum(v.weight for v in votes if v.side == "SELL")
    total = buy + sell + sum(v.weight for v in votes if v.side == "NEUTRAL")
    total = max(total, 1e-9)

    if buy > sell:
        side: Side = "BUY"
        dominance = buy / total
        edge = (buy - sell) / total
    elif sell > buy:
        side = "SELL"
        dominance = sell / total
        edge = (sell - buy) / total
    else:
        side = "WAIT"
        dominance = 0.5
        edge = 0.0

    # Confidence from dominance + edge (realistic band ~50–85)
    confidence = 50.0 + dominance * 25.0 + edge * 20.0
    confidence = float(np.clip(confidence, 50.0, 88.0))

    # Win probability slightly below raw confidence (honest framing)
    win_probability = float(np.clip(confidence - 3.0 + edge * 5.0, 48.0, 82.0))

    if side == "WAIT" or confidence < settings.min_confidence_to_trade:
        side = "WAIT"
        reasons = [v.reason for v in votes if v.side == "NEUTRAL"][:4]
        reasons.insert(0, "Indicators are mixed — no high-conviction setup right now")
        return side, confidence, win_probability, reasons

    reasons = [v.reason for v in votes if v.side == side]
    opposing = [v.reason for v in votes if v.side not in (side, "NEUTRAL")]
    if opposing:
        reasons.append(f"Caution: {opposing[0]}")

    return side, confidence, win_probability, reasons


def _round_lot(lot: float) -> float:
    step = settings.lot_step
    lot = max(settings.min_lot, min(settings.max_lot, lot))
    rounded = round(round(lot / step) * step, 2)
    return max(settings.min_lot, min(settings.max_lot, rounded))


def _lot_size(
    side: Side,
    entry: float,
    stop_loss: float,
    confidence: float,
    account_balance: float,
    risk_percent: float,
) -> tuple[float, float]:
    """Lot size scales with confidence and account risk vs SL distance."""
    if side == "WAIT" or entry <= 0:
        return 0.0, 0.0

    sl_distance = abs(entry - stop_loss)
    if sl_distance < 1e-6:
        return settings.min_lot, 0.0

    # Confidence scales risk from 40% → 100% of max risk %
    conf_factor = (confidence - 50.0) / 40.0
    conf_factor = float(np.clip(conf_factor, 0.35, 1.0))
    risk_pct = risk_percent * conf_factor
    risk_amount = account_balance * (risk_pct / 100.0)

    # For gold CFDs: loss ≈ lot * contract_size * price_move
    # lot = risk_amount / (sl_distance * contract_size)
    raw_lot = risk_amount / (sl_distance * settings.contract_size)
    lot = _round_lot(raw_lot)

    # Extra confidence bump for very strong signals (small)
    if confidence >= settings.high_confidence:
        lot = _round_lot(lot * 1.15)

    actual_risk = lot * settings.contract_size * sl_distance
    return lot, round(actual_risk, 2)


def _tp_sl(side: Side, entry: float, atr: float, snap: dict) -> tuple[float, float, float]:
    """ATR-first TP/SL with a capped structure nudge.

    Earlier versions pinned SL beyond the full 20-bar swing, which could make
    the stop ~$40–$50 wide while ATR only called for ~$10–$15. That felt like
    "SL is huge, TP is tiny." We now:
      1) size SL from ATR
      2) only nudge toward nearby structure if it stays inside max_sl_atr_mult
      3) always place TP farther than SL (min R:R)
    """
    atr = max(safe_nan(atr, entry * 0.002), entry * 0.0008)
    sl_dist = atr * settings.sl_atr_mult
    max_sl_dist = atr * settings.max_sl_atr_mult
    tp_dist = atr * settings.tp_atr_mult

    if side == "BUY":
        atr_sl = entry - sl_dist
        struct_sl = snap["swing_low"] - atr * 0.15
        # Prefer structure only when it is a *nearby* invalidation, not a canyon
        if np.isfinite(struct_sl) and atr_sl >= struct_sl >= entry - max_sl_dist:
            stop_loss = struct_sl
        else:
            stop_loss = atr_sl
        # Hard cap: never wider than max ATR multiple
        stop_loss = max(stop_loss, entry - max_sl_dist)
        sl_gap = entry - stop_loss
        take_profit = entry + max(tp_dist, sl_gap * settings.min_rr)
    elif side == "SELL":
        atr_sl = entry + sl_dist
        struct_sl = snap["swing_high"] + atr * 0.15
        if np.isfinite(struct_sl) and atr_sl <= struct_sl <= entry + max_sl_dist:
            stop_loss = struct_sl
        else:
            stop_loss = atr_sl
        stop_loss = min(stop_loss, entry + max_sl_dist)
        sl_gap = stop_loss - entry
        take_profit = entry - max(tp_dist, sl_gap * settings.min_rr)
    else:
        return entry, entry, 0.0

    rr = abs(take_profit - entry) / max(abs(entry - stop_loss), 1e-9)
    return round(stop_loss, 2), round(take_profit, 2), round(rr, 2)


def analyze_xauusd(
    interval: str = "15m",
    account_balance: float | None = None,
    risk_percent: float | None = None,
) -> TradeSignal:
    """Run full analysis and return a trade signal."""
    balance = account_balance if account_balance is not None else settings.account_balance
    risk_pct = risk_percent if risk_percent is not None else settings.max_risk_percent

    raw = fetch_ohlcv(interval=interval)
    df = enrich(raw)
    df = df.dropna()
    if len(df) < 60:
        raise RuntimeError("Not enough candle data to analyze. Try a higher timeframe.")

    snap = latest_snapshot(df)
    for key, val in list(snap.items()):
        snap[key] = safe_nan(float(val) if val is not None else 0.0)

    votes = _votes(snap)
    side, confidence, win_prob, reasons = _score(votes)
    entry = round(snap["price"], 2)
    atr = snap["atr"]

    stop_loss, take_profit, rr = _tp_sl(side, entry, atr, snap)
    lot, risk_amount = _lot_size(side, entry, stop_loss, confidence, balance, risk_pct)

    if side == "WAIT":
        lot = 0.0
        risk_amount = 0.0
        stop_loss = round(entry - atr * settings.sl_atr_mult, 2)
        take_profit = round(entry + atr * settings.tp_atr_mult, 2)
        rr = round(abs(take_profit - entry) / max(abs(entry - stop_loss), 1e-9), 2)

    sl_distance = round(abs(entry - stop_loss), 2)
    tp_distance = round(abs(entry - take_profit), 2)

    return TradeSignal(
        symbol=settings.display_symbol,
        side=side,
        lot_size=lot,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        sl_distance=sl_distance,
        tp_distance=tp_distance,
        win_probability=round(win_prob, 1),
        confidence=round(confidence, 1),
        risk_reward=rr,
        atr=round(atr, 2),
        timeframe=interval,
        reasons=reasons,
        indicator_votes=[asdict(v) for v in votes],
        account_balance=balance,
        risk_amount=risk_amount,
        candles=candles_to_list(df),
        snapshot={
            "rsi": round(snap["rsi"], 2),
            "macd": round(snap["macd"], 4),
            "macd_signal": round(snap["macd_signal"], 4),
            "adx": round(snap["adx"], 2),
            "ema_fast": round(snap["ema_fast"], 2),
            "ema_slow": round(snap["ema_slow"], 2),
            "ema_trend": round(snap["ema_trend"], 2),
            "bb_pct": round(snap["bb_pct"], 3),
            "stoch_k": round(snap["stoch_k"], 2),
            "stoch_d": round(snap["stoch_d"], 2),
        },
    )


def quick_backtest_hint(df: pd.DataFrame | None = None, interval: str = "15m") -> dict[str, Any]:
    """Lightweight recent-window hit-rate hint (not a full backtester)."""
    if df is None:
        df = enrich(fetch_ohlcv(interval=interval)).dropna()

    hits = 0
    total = 0
    for i in range(60, len(df) - 5):
        window = df.iloc[: i + 1]
        snap = latest_snapshot(window)
        for key, val in list(snap.items()):
            snap[key] = safe_nan(float(val) if val is not None else 0.0)
        side, conf, _, _ = _score(_votes(snap))
        if side == "WAIT" or conf < settings.min_confidence_to_trade:
            continue
        entry = float(window.iloc[-1]["close"])
        future = df.iloc[i + 1 : i + 6]
        if side == "BUY":
            total += 1
            if float(future["high"].max()) >= entry + snap["atr"] * 1.0:
                hits += 1
        elif side == "SELL":
            total += 1
            if float(future["low"].min()) <= entry - snap["atr"] * 1.0:
                hits += 1

    rate = round((hits / total) * 100, 1) if total else None
    return {"sample_signals": total, "forward_hit_rate_pct": rate}
