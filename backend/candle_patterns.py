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


def candle_votes(df: pd.DataFrame) -> list[CandleVote]:
    """Score the latest candles using classic price-action patterns."""
    if len(df) < 5:
        return [CandleVote("Data", "NEUTRAL", 0.1, "Need more candles")]

    snap = candle_snapshot(df)
    cur = _row(df.iloc[-1])
    prev = _row(df.iloc[-2])

    votes: list[CandleVote] = []

    # Single-candle patterns on the latest bar
    if _is_doji(cur):
        votes.append(CandleVote("Doji", "NEUTRAL", 0.8, "Doji — indecision, wait for confirmation"))
    elif _is_hammer(cur):
        votes.append(CandleVote("Hammer", "BUY", 1.0, "Hammer / pin bar — rejection from lows"))
    elif _is_shooting_star(cur):
        votes.append(CandleVote("Shooting Star", "SELL", 1.0, "Shooting star — rejection from highs"))
    elif cur["bullish"] and cur["body_pct"] >= 0.7:
        votes.append(CandleVote("Marubozu", "BUY", 0.9, "Strong bullish marubozu — momentum up"))
    elif cur["bearish"] and cur["body_pct"] >= 0.7:
        votes.append(CandleVote("Marubozu", "SELL", 0.9, "Strong bearish marubozu — momentum down"))
    else:
        votes.append(
            CandleVote(
                "Last Candle",
                "BUY" if cur["bullish"] else "SELL",
                0.35,
                f"Latest candle {'bullish' if cur['bullish'] else 'bearish'} ({cur['body_pct']*100:.0f}% body)",
            )
        )

    # Two-candle patterns
    if _bullish_engulfing(prev, cur):
        votes.append(CandleVote("Engulfing", "BUY", 1.2, "Bullish engulfing — buyers absorbed sellers"))
    elif _bearish_engulfing(prev, cur):
        votes.append(CandleVote("Engulfing", "SELL", 1.2, "Bearish engulfing — sellers absorbed buyers"))
    elif _inside_bar(prev, cur):
        if cur["close"] > prev["high"]:
            votes.append(CandleVote("Inside Bar", "BUY", 1.0, "Inside bar breakout to the upside"))
        elif cur["close"] < prev["low"]:
            votes.append(CandleVote("Inside Bar", "SELL", 1.0, "Inside bar breakdown to the downside"))
        else:
            votes.append(CandleVote("Inside Bar", "NEUTRAL", 0.6, "Inside bar — compression, wait for break"))
    else:
        votes.append(CandleVote("Engulfing", "NEUTRAL", 0.2, "No engulfing pattern"))

    # Three-candle stars
    if len(df) >= 3:
        c1 = _row(df.iloc[-3])
        c2 = _row(df.iloc[-2])
        c3r = _row(df.iloc[-1])
        if _morning_star(c1, c2, c3r):
            votes.append(CandleVote("Morning Star", "BUY", 1.3, "Morning star — bullish reversal sequence"))
        elif _evening_star(c1, c2, c3r):
            votes.append(CandleVote("Evening Star", "SELL", 1.3, "Evening star — bearish reversal sequence"))
        else:
            votes.append(CandleVote("Star Pattern", "NEUTRAL", 0.2, "No star reversal pattern"))

    votes.append(_structure_vote(df))
    votes.append(_support_resistance_vote(snap, cur))

    # Momentum: last 3 closes direction
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

    return {
        "patterns": ", ".join(patterns) if patterns else "None detected",
        "last_candle": "Bullish" if cur["bullish"] else "Bearish",
        "body_pct": round(cur["body_pct"] * 100, 1),
        "avg_range": round(snap["avg_range"], 2),
        "swing_high": round(snap["swing_high"], 2),
        "swing_low": round(snap["swing_low"], 2),
    }
