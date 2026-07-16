"""Unit tests for signal scoring and lot sizing (no live market data)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.indicators import enrich, latest_snapshot
from backend.signal_engine import _lot_size, _score, _tp_sl, _votes


def _synthetic_ohlcv(n: int = 160, trend: float = 0.4) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    prices = [2000.0]
    for _ in range(1, n):
        prices.append(prices[-1] + trend + float(rng.normal(0, 1.2)))
    close = np.array(prices)
    high = close + rng.uniform(0.5, 2.5, size=n)
    low = close - rng.uniform(0.5, 2.5, size=n)
    open_ = close + rng.normal(0, 0.8, size=n)
    volume = rng.integers(100, 1000, size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="15min")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_enrich_adds_indicators():
    df = enrich(_synthetic_ohlcv())
    for col in ("rsi", "macd", "atr", "ema_fast", "adx", "bb_pct"):
        assert col in df.columns


def test_bullish_votes_prefer_buy():
    df = enrich(_synthetic_ohlcv(trend=0.8)).dropna()
    snap = latest_snapshot(df)
    votes = _votes(snap)
    side, confidence, win_prob, reasons = _score(
        votes,
        wait_msg="Indicators are mixed — no high-conviction setup right now",
    )
    assert side in {"BUY", "SELL", "WAIT"}
    assert 48 <= win_prob <= 88
    assert 50 <= confidence <= 88
    assert reasons
    # Strong uptrend synthetic series should lean BUY more often than SELL
    buy_w = sum(v.weight for v in votes if v.side == "BUY")
    sell_w = sum(v.weight for v in votes if v.side == "SELL")
    assert buy_w >= sell_w


def test_lot_scales_with_confidence():
    cs = 100.0
    low_lot, _ = _lot_size("BUY", 2300, 2290, confidence=55, account_balance=1000, risk_percent=2, contract_size=cs)
    high_lot, _ = _lot_size("BUY", 2300, 2290, confidence=85, account_balance=1000, risk_percent=2, contract_size=cs)
    assert high_lot >= low_lot
    assert low_lot >= 0.01


def test_tp_sl_buy_has_positive_rr():
    snap = {"swing_low": 2280.0, "swing_high": 2320.0}
    sl, tp, rr = _tp_sl("BUY", 2300.0, atr=8.0, snap=snap)
    assert sl < 2300
    assert tp > 2300
    assert rr >= 1.8
    assert abs(tp - 2300) > abs(2300 - sl)


def test_tp_sl_ignores_distant_swing():
    """Far swing highs must not blow SL out to $40+ when ATR is ~$8."""
    atr = 8.0
    entry = 3980.0
    snap = {"swing_low": 3970.0, "swing_high": 4022.0}  # ~$42 away
    sl, tp, rr = _tp_sl("SELL", entry, atr=atr, snap=snap)
    sl_dist = abs(sl - entry)
    tp_dist = abs(entry - tp)
    assert sl_dist <= atr * 2.0 + 1e-6
    assert tp_dist > sl_dist
    assert rr >= 1.8


def test_wait_lot_is_zero():
    lot, risk = _lot_size("WAIT", 2300, 2290, confidence=60, account_balance=1000, risk_percent=2, contract_size=100.0)
    assert lot == 0.0
    assert risk == 0.0
