"""Pure price-action candlestick pattern detection (no indicators)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Side = Literal["BUY", "SELL", "NEUTRAL"]


@dataclass
class CandleVote:
    name: str
    side: Side
    weight: float
    reason: str


def _row(row: pd.Series) -> dict[str, float]:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "body": body,
        "range": rng,
        "upper_wick": upper,
        "lower_wick": lower,
        "bullish": c >= o,
        "bearish": c < o,
        "body_pct": body / rng,
        "upper_pct": upper / rng,
        "lower_pct": lower / rng,
    }


def average_range(df: pd.DataFrame, window: int = 14) -> float:
    ranges = (df["high"] - df["low"]).tail(window)
    return float(ranges.mean()) if len(ranges) else 0.0


def candle_snapshot(df: pd.DataFrame) -> dict[str, float]:
    """Price-action snapshot without indicator columns."""
    tail = df.tail(20)
    price = float(df.iloc[-1]["close"])
    swing_high = float(tail["high"].max())
    swing_low = float(tail["low"].min())
    avg_rng = average_range(df)
    return {
        "price": price,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "avg_range": max(avg_rng, price * 0.0008),
        "mid_range": (swing_high + swing_low) / 2,
    }


def _is_doji(c: dict) -> bool:
    return c["body_pct"] <= 0.12 and c["range"] > 0


def _is_hammer(c: dict) -> bool:
    return (
        c["lower_pct"] >= 0.55
        and c["upper_pct"] <= 0.2
        and c["body_pct"] <= 0.35
        and c["range"] > 0
    )


def _is_shooting_star(c: dict) -> bool:
    return (
        c["upper_pct"] >= 0.55
        and c["lower_pct"] <= 0.2
        and c["body_pct"] <= 0.35
        and c["range"] > 0
    )


def _bullish_engulfing(prev: dict, cur: dict) -> bool:
    return (
        prev["bearish"]
        and cur["bullish"]
        and cur["open"] <= prev["close"]
        and cur["close"] >= prev["open"]
        and cur["body"] > prev["body"] * 0.9
    )


def _bearish_engulfing(prev: dict, cur: dict) -> bool:
    return (
        prev["bullish"]
        and cur["bearish"]
        and cur["open"] >= prev["close"]
        and cur["close"] <= prev["open"]
        and cur["body"] > prev["body"] * 0.9
    )


def _inside_bar(prev: dict, cur: dict) -> bool:
    return cur["high"] <= prev["high"] and cur["low"] >= prev["low"]


def _morning_star(c1: dict, c2: dict, c3: dict) -> bool:
    return (
        c1["bearish"]
        and c1["body_pct"] >= 0.45
        and c2["body_pct"] <= 0.35
        and c3["bullish"]
        and c3["close"] > (c1["open"] + c1["close"]) / 2
    )


def _evening_star(c1: dict, c2: dict, c3: dict) -> bool:
    return (
        c1["bullish"]
        and c1["body_pct"] >= 0.45
        and c2["body_pct"] <= 0.35
        and c3["bearish"]
        and c3["close"] < (c1["open"] + c1["close"]) / 2
    )


def _structure_vote(df: pd.DataFrame) -> CandleVote:
    """Higher highs/lows or lower highs/lows over recent swings."""
    if len(df) < 8:
        return CandleVote("Structure", "NEUTRAL", 0.3, "Not enough candles for structure")

    highs = df["high"].tail(8).values
    lows = df["low"].tail(8).values
    mid = len(highs) // 2
    first_high, second_high = float(highs[:mid].max()), float(highs[mid:].max())
    first_low, second_low = float(lows[:mid].min()), float(lows[mid:].min())

    if second_high > first_high and second_low > first_low:
        return CandleVote("Structure", "BUY", 1.0, "Higher highs and higher lows (uptrend)")
    if second_high < first_high and second_low < first_low:
        return CandleVote("Structure", "SELL", 1.0, "Lower highs and lower lows (downtrend)")
    if second_high > first_high:
        return CandleVote("Structure", "BUY", 0.5, "Higher highs forming")
    if second_low < first_low:
        return CandleVote("Structure", "SELL", 0.5, "Lower lows forming")
    return CandleVote("Structure", "NEUTRAL", 0.3, "Sideways / mixed structure")


def _support_resistance_vote(snap: dict, cur: dict) -> CandleVote:
    price = snap["price"]
    near_support = abs(price - snap["swing_low"]) <= snap["avg_range"] * 0.6
    near_resistance = abs(snap["swing_high"] - price) <= snap["avg_range"] * 0.6

    if near_support and cur["bullish"]:
        return CandleVote("S/R", "BUY", 0.9, "Bullish candle bouncing from support zone")
    if near_resistance and cur["bearish"]:
        return CandleVote("S/R", "SELL", 0.9, "Bearish candle rejecting resistance zone")
    if near_support:
        return CandleVote("S/R", "BUY", 0.6, "Price testing recent support")
    if near_resistance:
        return CandleVote("S/R", "SELL", 0.6, "Price testing recent resistance")
    if price > snap["mid_range"]:
        return CandleVote("S/R", "BUY", 0.35, "Price holding upper half of range")
    if price < snap["mid_range"]:
        return CandleVote("S/R", "SELL", 0.35, "Price holding lower half of range")
    return CandleVote("S/R", "NEUTRAL", 0.2, "Mid-range price action")


# ---------------------------------------------------------------------------
# Playbook layers for candle mode: top-down bias, level gating, volume, RSI
# divergence and MA-pullback. Everything is computed inline so this module
# stays self-contained (no shared indicator dependency).
# ---------------------------------------------------------------------------


def _ema(series: pd.Series, span: int) -> float:
    """NaN-free EMA (adjust=False seeds from the first value)."""
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _rsi_series(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = up / down.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def _rsi_divergence(df: pd.DataFrame, rsi: pd.Series, lookback: int = 20) -> tuple[int, int]:
    """Bullish/bearish divergence flags over a recent window."""
    if len(df) < lookback:
        lookback = len(df)
    if lookback < 6:
        return 0, 0
    seg = df.tail(lookback).reset_index(drop=True)
    rseg = rsi.tail(lookback).reset_index(drop=True)
    half = len(seg) // 2
    early_low_i = int(seg["low"].iloc[:half].values.argmin())
    late_low_i = half + int(seg["low"].iloc[half:].values.argmin())
    early_high_i = int(seg["high"].iloc[:half].values.argmax())
    late_high_i = half + int(seg["high"].iloc[half:].values.argmax())

    price_ll = float(seg["low"].iloc[late_low_i]) < float(seg["low"].iloc[early_low_i])
    rsi_hl = float(rseg.iloc[late_low_i]) > float(rseg.iloc[early_low_i])
    price_hh = float(seg["high"].iloc[late_high_i]) > float(seg["high"].iloc[early_high_i])
    rsi_lh = float(rseg.iloc[late_high_i]) < float(rseg.iloc[early_high_i])
    return int(price_ll and rsi_hl), int(price_hh and rsi_lh)


def _playbook_context(df: pd.DataFrame, snap: dict) -> dict:
    """Compute the confluence context the playbook needs on top of patterns."""
    close = df["close"]
    price = snap["price"]
    atr = snap["avg_range"]
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)

    # Fib 38.2–61.8% retracement zones off the recent swing range.
    rng = snap["swing_high"] - snap["swing_low"]
    fib_bull_zone = fib_bear_zone = 0
    if rng > 0:
        fib_bull_zone = int(snap["swing_high"] - 0.618 * rng <= price <= snap["swing_high"] - 0.382 * rng)
        fib_bear_zone = int(snap["swing_low"] + 0.382 * rng <= price <= snap["swing_low"] + 0.618 * rng)

    tol = atr * 0.6
    near_support = int(abs(price - snap["swing_low"]) <= tol)
    near_resistance = int(abs(snap["swing_high"] - price) <= tol)

    vol_ma_series = df["volume"].rolling(20, min_periods=1).mean()
    vol_ma = float(vol_ma_series.iloc[-1])
    vol_now = float(df["volume"].iloc[-1])
    vol_ratio = (vol_now / vol_ma) if vol_ma > 0 else 0.0

    bull_div, bear_div = _rsi_divergence(df, _rsi_series(close))

    low = float(df["low"].iloc[-1])
    high = float(df["high"].iloc[-1])
    pullback_tag = int(low <= ema50 + atr * 0.25 and high >= ema50 - atr * 0.25)

    return {
        "ema50": ema50,
        "ema200": ema200,
        "at_bull_level": bool(fib_bull_zone or near_support),
        "at_bear_level": bool(fib_bear_zone or near_resistance),
        "vol_ratio": vol_ratio,
        "bull_div": bool(bull_div),
        "bear_div": bool(bear_div),
        "pullback_tag": bool(pullback_tag),
    }


def _dominant_pattern(df: pd.DataFrame) -> tuple[str, int]:
    """Pick the strongest playbook pattern on the latest candle(s).

    Returns (name, direction) where direction is 1 bull, -1 bear, 0 neutral.
    Priority: 3-candle > 2-candle > single-candle.
    """
    cur = _row(df.iloc[-1])
    prev = _row(df.iloc[-2])

    if len(df) >= 3:
        c1, c2, c3 = _row(df.iloc[-3]), _row(df.iloc[-2]), _row(df.iloc[-1])
        if _morning_star(c1, c2, c3):
            return "morning star", 1
        if _evening_star(c1, c2, c3):
            return "evening star", -1

    if _bullish_engulfing(prev, cur):
        return "bullish engulfing", 1
    if _bearish_engulfing(prev, cur):
        return "bearish engulfing", -1
    if _inside_bar(prev, cur):
        if cur["close"] > prev["high"]:
            return "inside-bar breakout", 1
        if cur["close"] < prev["low"]:
            return "inside-bar breakdown", -1
        return "inside bar (coiling)", 0

    if _is_doji(cur):
        return "doji", 0
    if _is_hammer(cur):
        return "hammer / pin bar", 1
    if _is_shooting_star(cur):
        return "shooting star", -1
    if cur["bullish"] and cur["body_pct"] >= 0.7:
        return "bullish marubozu", 1
    if cur["bearish"] and cur["body_pct"] >= 0.7:
        return "bearish marubozu", -1
    return "no clean pattern", 0


def candle_votes(df: pd.DataFrame) -> list[CandleVote]:
    """Score the latest candles using the playbook applied to price action."""
    if len(df) < 5:
        return [CandleVote("Data", "NEUTRAL", 0.1, "Need more candles")]

    snap = candle_snapshot(df)
    cur = _row(df.iloc[-1])
    ctx = _playbook_context(df, snap)
    price = snap["price"]

    votes: list[CandleVote] = []

    # LAYER 1 — Top-down market bias (playbook §1): price vs 50 & 200 EMA.
    ema50, ema200 = ctx["ema50"], ctx["ema200"]
    if price > ema50 and price > ema200 and ema50 >= ema200:
        votes.append(CandleVote("Market Bias", "BUY", 1.6, "Price above 50 & 200 EMA (bullish bias)"))
    elif price < ema50 and price < ema200 and ema50 <= ema200:
        votes.append(CandleVote("Market Bias", "SELL", 1.6, "Price below 50 & 200 EMA (bearish bias)"))
    else:
        votes.append(CandleVote("Market Bias", "NEUTRAL", 0.6, "Price chopping between 50/200 EMA — range mode"))

    # LAYER 2 — Entry trigger at a pre-marked level (playbook §2): the dominant
    # candle pattern only counts when it prints at a Fib zone / swing S/R.
    name, pdir = _dominant_pattern(df)
    if pdir > 0 and ctx["at_bull_level"]:
        votes.append(CandleVote("Candle Trigger", "BUY", 1.4, f"{name} at support/Fib zone"))
    elif pdir < 0 and ctx["at_bear_level"]:
        votes.append(CandleVote("Candle Trigger", "SELL", 1.4, f"{name} at resistance/Fib zone"))
    elif name == "doji":
        votes.append(CandleVote("Candle Trigger", "NEUTRAL", 0.4, "Doji at level — wait for confirmation"))
    elif pdir != 0:
        votes.append(CandleVote("Candle Trigger", "NEUTRAL", 0.3, f"{name} but not at a key level"))
    else:
        votes.append(CandleVote("Candle Trigger", "NEUTRAL", 0.2, "No trigger candle at a key level"))

    # Price-action structure and S/R confluence.
    votes.append(_structure_vote(df))
    votes.append(_support_resistance_vote(snap, cur))

    # LAYER 3 — Confirmation (playbook §3): volume, RSI divergence, pullback.
    vol_ratio = ctx["vol_ratio"]
    if vol_ratio >= 1.2:
        vol_side: Side = "BUY" if cur["bullish"] else "SELL"
        votes.append(CandleVote("Volume", vol_side, 0.7, f"Volume {vol_ratio:.1f}x average — real participation"))
    elif vol_ratio and vol_ratio < 0.7:
        votes.append(CandleVote("Volume", "NEUTRAL", 0.3, f"Volume {vol_ratio:.1f}x average — thin, low conviction"))
    else:
        votes.append(CandleVote("Volume", "NEUTRAL", 0.2, "Volume near average"))

    if ctx["bull_div"]:
        votes.append(CandleVote("RSI Divergence", "BUY", 0.9, "Bullish RSI divergence at reversal zone"))
    elif ctx["bear_div"]:
        votes.append(CandleVote("RSI Divergence", "SELL", 0.9, "Bearish RSI divergence at reversal zone"))
    else:
        votes.append(CandleVote("RSI Divergence", "NEUTRAL", 0.2, "No RSI divergence"))

    if ctx["pullback_tag"]:
        if price > ema200 and ema50 >= ema200:
            votes.append(CandleVote("MA Pullback", "BUY", 0.8, "Pullback tagging 50 EMA in uptrend — continuation"))
        elif price < ema200 and ema50 <= ema200:
            votes.append(CandleVote("MA Pullback", "SELL", 0.8, "Pullback tagging 50 EMA in downtrend — continuation"))
        else:
            votes.append(CandleVote("MA Pullback", "NEUTRAL", 0.2, "Price at 50 EMA but trend unclear"))
    else:
        votes.append(CandleVote("MA Pullback", "NEUTRAL", 0.2, "No 50 EMA pullback tag"))

    # Momentum: last 3 closes direction (price-action confirmation).
    closes = df["close"].tail(3).values
    if closes[-1] > closes[-2] > closes[-3]:
        votes.append(CandleVote("Momentum", "BUY", 0.7, "Three rising closes in a row"))
    elif closes[-1] < closes[-2] < closes[-3]:
        votes.append(CandleVote("Momentum", "SELL", 0.7, "Three falling closes in a row"))
    else:
        votes.append(CandleVote("Momentum", "NEUTRAL", 0.25, "Mixed short-term momentum"))

    return votes


def pattern_snapshot(df: pd.DataFrame) -> dict[str, str | float]:
    """Human-readable snapshot for the UI."""
    if len(df) < 2:
        return {}
    snap = candle_snapshot(df)
    cur = _row(df.iloc[-1])
    prev = _row(df.iloc[-2])
    patterns: list[str] = []
    if _is_doji(cur):
        patterns.append("Doji")
    if _is_hammer(cur):
        patterns.append("Hammer")
    if _is_shooting_star(cur):
        patterns.append("Shooting Star")
    if _bullish_engulfing(prev, cur):
        patterns.append("Bullish Engulfing")
    if _bearish_engulfing(prev, cur):
        patterns.append("Bearish Engulfing")
    if _inside_bar(prev, cur):
        patterns.append("Inside Bar")
    if len(df) >= 3:
        c1 = _row(df.iloc[-3])
        c2 = _row(df.iloc[-2])
        c3 = _row(df.iloc[-1])
        if _morning_star(c1, c2, c3):
            patterns.append("Morning Star")
        if _evening_star(c1, c2, c3):
            patterns.append("Evening Star")

    ctx = _playbook_context(df, snap)
    price = snap["price"]
    if price > ctx["ema50"] and price > ctx["ema200"]:
        bias = "Bullish (above 50 & 200 EMA)"
    elif price < ctx["ema50"] and price < ctx["ema200"]:
        bias = "Bearish (below 50 & 200 EMA)"
    else:
        bias = "Range (between 50/200 EMA)"

    if ctx["at_bull_level"]:
        at_level = "At support / bullish Fib zone"
    elif ctx["at_bear_level"]:
        at_level = "At resistance / bearish Fib zone"
    else:
        at_level = "Not at a key level"

    return {
        "patterns": ", ".join(patterns) if patterns else "None detected",
        "last_candle": "Bullish" if cur["bullish"] else "Bearish",
        "body_pct": round(cur["body_pct"] * 100, 1),
        "bias": bias,
        "at_key_level": at_level,
        "volume_x_avg": round(ctx["vol_ratio"], 2),
        "avg_range": round(snap["avg_range"], 2),
        "swing_high": round(snap["swing_high"], 2),
        "swing_low": round(snap["swing_low"], 2),
    }
