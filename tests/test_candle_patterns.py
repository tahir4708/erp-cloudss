"""Tests for candlestick pattern analysis."""

from __future__ import annotations

import pandas as pd

from backend.candle_patterns import (
    _bearish_engulfing,
    _bullish_engulfing,
    _dark_cloud_cover,
    _is_hammer,
    _is_shooting_star,
    _piercing,
    _row,
    _three_black_crows,
    _three_white_soldiers,
    candle_votes,
)
from backend.signal_engine import analyze_xauusd


def _candle(open_: float, high: float, low: float, close: float) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": 100}


def test_bullish_engulfing_detected():
    prev = _row(pd.Series(_candle(100, 101, 95, 96)))
    cur = _row(pd.Series(_candle(95.5, 103, 94, 102)))
    assert _bullish_engulfing(prev, cur)


def test_bearish_engulfing_detected():
    prev = _row(pd.Series(_candle(100, 105, 99, 104)))
    cur = _row(pd.Series(_candle(104.5, 105, 97, 98)))
    assert _bearish_engulfing(prev, cur)


def test_hammer_detected():
    c = _row(pd.Series(_candle(100, 101, 92, 100.5)))
    assert _is_hammer(c)


def test_shooting_star_detected():
    c = _row(pd.Series(_candle(100, 109, 99.5, 100)))
    assert _is_shooting_star(c)


def test_piercing_pattern_detected():
    prev = _row(pd.Series(_candle(110, 111, 100, 101)))  # long red
    cur = _row(pd.Series(_candle(99, 108, 98, 107)))  # green closes >50% into red
    assert _piercing(prev, cur)


def test_dark_cloud_cover_detected():
    prev = _row(pd.Series(_candle(100, 111, 99, 110)))  # long green
    cur = _row(pd.Series(_candle(112, 113, 102, 103)))  # red closes <50% into green
    assert _dark_cloud_cover(prev, cur)


def test_three_white_soldiers_detected():
    c1 = _row(pd.Series(_candle(100, 105.2, 99.8, 105)))
    c2 = _row(pd.Series(_candle(103, 110.2, 102.8, 110)))
    c3 = _row(pd.Series(_candle(108, 116.2, 107.8, 116)))
    assert _three_white_soldiers(c1, c2, c3)


def test_three_black_crows_detected():
    c1 = _row(pd.Series(_candle(116, 116.2, 110.8, 111)))
    c2 = _row(pd.Series(_candle(113, 113.2, 105.8, 106)))
    c3 = _row(pd.Series(_candle(108, 108.2, 99.8, 100)))
    assert _three_black_crows(c1, c2, c3)


def test_candle_votes_on_downtrend_series():
    rows = []
    price = 4000.0
    for i in range(40):
        o = price
        c = price - 2.5
        rows.append(_candle(o, o + 1, c - 1.5, c))
        price = c
    df = pd.DataFrame(rows)
    votes = candle_votes(df)
    assert len(votes) >= 5
    sell_weight = sum(v.weight for v in votes if v.side == "SELL")
    buy_weight = sum(v.weight for v in votes if v.side == "BUY")
    assert sell_weight >= buy_weight


def test_analyze_candles_mode_returns_signal():
    signal = analyze_xauusd(interval="1h", mode="candles")
    data = signal.to_dict()
    assert data["analysis_mode"] == "candles"
    assert data["side"] in {"BUY", "SELL", "WAIT"}
    assert data["entry"] > 0
    assert "patterns" in data["snapshot"]
    assert "dominant_pattern" in data["snapshot"]
    assert "pattern_signal" in data["snapshot"]
