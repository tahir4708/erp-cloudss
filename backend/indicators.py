"""Technical indicators for XAU/USD analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add indicator columns used by the signal engine."""
    data = df.copy()
    close = data["close"]
    high = data["high"]
    low = data["low"]

    data["ema_fast"] = EMAIndicator(close, window=9).ema_indicator()
    data["ema_slow"] = EMAIndicator(close, window=21).ema_indicator()
    data["ema_trend"] = EMAIndicator(close, window=50).ema_indicator()
    # 200 EMA = macro/top-down bias (playbook: price vs 50 & 200 sets bias).
    # Computed via ewm (adjust=False) so it is NaN-free even on short windows
    # and does not force the downstream dropna() to discard most of the data.
    data["ema_long"] = close.ewm(span=200, adjust=False).mean()

    macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
    data["macd"] = macd.macd()
    data["macd_signal"] = macd.macd_signal()
    data["macd_hist"] = macd.macd_diff()

    data["rsi"] = RSIIndicator(close, window=14).rsi()

    stoch = StochasticOscillator(high, low, close, window=14, smooth_window=3)
    data["stoch_k"] = stoch.stoch()
    data["stoch_d"] = stoch.stoch_signal()

    bb = BollingerBands(close, window=20, window_dev=2)
    data["bb_high"] = bb.bollinger_hband()
    data["bb_mid"] = bb.bollinger_mavg()
    data["bb_low"] = bb.bollinger_lband()
    data["bb_pct"] = bb.bollinger_pband()

    atr = AverageTrueRange(high, low, close, window=14)
    data["atr"] = atr.average_true_range()

    adx = ADXIndicator(high, low, close, window=14)
    data["adx"] = adx.adx()
    data["adx_pos"] = adx.adx_pos()
    data["adx_neg"] = adx.adx_neg()

    # Simple swing support / resistance
    data["swing_high"] = high.rolling(20).max()
    data["swing_low"] = low.rolling(20).min()

    # Volume confirmation baseline (playbook: entry candle should print
    # above-average volume). min_periods=1 keeps it NaN-free.
    data["vol_ma"] = data["volume"].rolling(20, min_periods=1).mean()

    return data


# ---------------------------------------------------------------------------
# Playbook building blocks: candle patterns, Fib zones, RSI divergence.
# ---------------------------------------------------------------------------

# Pattern codes -> (human name, direction). direction: 1 bullish, -1 bearish, 0 neutral.
PATTERN_LIBRARY: dict[int, tuple[str, int]] = {
    0: ("no clean pattern", 0),
    1: ("bullish pin bar / hammer", 1),
    2: ("bearish shooting star", -1),
    3: ("bullish engulfing", 1),
    4: ("bearish engulfing", -1),
    5: ("morning star", 1),
    6: ("evening star", -1),
    7: ("bullish inside-bar breakout", 1),
    8: ("bearish inside-bar breakout", -1),
    9: ("doji (indecision)", 0),
}


def _metrics(o: float, h: float, low_: float, c: float) -> tuple[float, float, float, float]:
    rng = max(h - low_, 1e-9)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - low_
    return rng, body, upper_wick, lower_wick


def detect_candle_pattern(df: pd.DataFrame) -> int:
    """Classify the most recent candle against the playbook pattern set.

    Returns a code from ``PATTERN_LIBRARY``. Only single/2/3-candle structures
    the playbook watches for are recognised; anything else returns 0.
    """
    if len(df) < 3:
        return 0

    c0 = df.iloc[-1]
    c1 = df.iloc[-2]
    c2 = df.iloc[-3]

    o0, h0, l0, cl0 = float(c0["open"]), float(c0["high"]), float(c0["low"]), float(c0["close"])
    o1, h1, l1, cl1 = float(c1["open"]), float(c1["high"]), float(c1["low"]), float(c1["close"])
    o2, l2, cl2 = float(c2["open"]), float(c2["low"]), float(c2["close"])

    rng0, body0, upper0, lower0 = _metrics(o0, h0, l0, cl0)
    _, body1, _, _ = _metrics(o1, h1, l1, cl1)

    # Doji first — indecision, the playbook says wait for confirmation.
    if body0 <= rng0 * 0.1:
        return 9

    # Pin bar / hammer: long lower wick, small body sitting in the upper half.
    if lower0 >= body0 * 2 and upper0 <= body0 and cl0 >= (h0 + l0) / 2:
        return 1
    # Shooting star: long upper wick, small body in the lower half.
    if upper0 >= body0 * 2 and lower0 <= body0 and cl0 <= (h0 + l0) / 2:
        return 2

    # Engulfing: current real body fully engulfs the prior body.
    bull_engulf = cl1 < o1 and cl0 > o0 and o0 <= cl1 and cl0 >= o1
    bear_engulf = cl1 > o1 and cl0 < o0 and o0 >= cl1 and cl0 <= o1
    if bull_engulf:
        return 3
    if bear_engulf:
        return 4

    # Morning / evening star: big candle, small-bodied middle, strong reversal.
    rng2, _, _, _ = _metrics(o2, float(c2["high"]), l2, cl2)
    mid2 = (o2 + cl2) / 2
    small_middle = body1 <= rng2 * 0.5
    if cl2 < o2 and small_middle and cl0 > o0 and cl0 >= mid2 and body0 >= rng0 * 0.5:
        return 5
    if cl2 > o2 and small_middle and cl0 < o0 and cl0 <= mid2 and body0 >= rng0 * 0.5:
        return 6

    # Inside-bar breakout: prior candle coiled inside the one before it, then
    # the latest candle breaks the inside bar's range.
    inside_prev = h1 < float(c2["high"]) and l1 > l2
    if inside_prev and cl0 > h1:
        return 7
    if inside_prev and cl0 < l1:
        return 8

    return 0


def _rsi_divergence(df: pd.DataFrame, lookback: int = 20) -> tuple[int, int]:
    """Detect simple RSI/price divergence over a recent window.

    Returns (bull_div, bear_div) as 0/1 flags. Bullish divergence = price
    prints a lower low while RSI prints a higher low; bearish is the mirror.
    """
    if "rsi" not in df.columns or len(df) < lookback:
        return 0, 0
    seg = df.tail(lookback)
    half = len(seg) // 2
    early, late = seg.iloc[:half], seg.iloc[half:]
    if early.empty or late.empty:
        return 0, 0

    price_ll = float(late["low"].min()) < float(early["low"].min())
    rsi_hl = float(late.iloc[late["low"].values.argmin()]["rsi"]) > float(
        early.iloc[early["low"].values.argmin()]["rsi"]
    )
    price_hh = float(late["high"].max()) > float(early["high"].max())
    rsi_lh = float(late.iloc[late["high"].values.argmax()]["rsi"]) < float(
        early.iloc[early["high"].values.argmax()]["rsi"]
    )
    return int(price_ll and rsi_hl), int(price_hh and rsi_lh)


def latest_snapshot(df: pd.DataFrame) -> dict:
    """Return the most recent indicator values as a plain dict."""
    row = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else row

    def f(key: str) -> float:
        val = row[key]
        return float(val) if pd.notna(val) else float("nan")

    price = f("close")
    atr = f("atr")
    swing_high = f("swing_high")
    swing_low = f("swing_low")

    # --- Fibonacci retracement zones off the recent swing range -----------
    # For a bullish pullback we want price back in the 38.2%–61.8% discount
    # zone of the last up-leg; for shorts, the premium bounce zone.
    rng = swing_high - swing_low if pd.notna(swing_high) and pd.notna(swing_low) else 0.0
    fib_bull_zone = 0
    fib_bear_zone = 0
    if rng > 0:
        bull_shallow = swing_high - 0.382 * rng
        bull_deep = swing_high - 0.618 * rng
        bear_shallow = swing_low + 0.382 * rng
        bear_deep = swing_low + 0.618 * rng
        fib_bull_zone = int(bull_deep <= price <= bull_shallow)
        fib_bear_zone = int(bear_shallow <= price <= bear_deep)

    # --- Proximity to swing structure (prior S/R) -------------------------
    tol = atr * 0.5 if pd.notna(atr) and atr > 0 else 0.0
    near_support = int(pd.notna(swing_low) and abs(price - swing_low) <= tol)
    near_resistance = int(pd.notna(swing_high) and abs(price - swing_high) <= tol)

    # A pattern is only actionable if it fires at a pre-marked level.
    at_bull_level = int(bool(fib_bull_zone) or bool(near_support))
    at_bear_level = int(bool(fib_bear_zone) or bool(near_resistance))

    # --- Candle pattern + volume + divergence -----------------------------
    pattern_code = detect_candle_pattern(df)
    _, pattern_dir = PATTERN_LIBRARY.get(pattern_code, ("", 0))

    vol_ma = f("vol_ma")
    vol_now = f("volume")
    vol_ratio = (vol_now / vol_ma) if pd.notna(vol_ma) and vol_ma > 0 else 0.0

    bull_div, bear_div = _rsi_divergence(df)

    # --- MA pullback continuation (price tagging the 50 EMA in a trend) ----
    ema_trend = f("ema_trend")
    pullback_tag = int(pd.notna(ema_trend) and pd.notna(atr) and atr > 0 and f("low") <= ema_trend + atr * 0.25 and f("high") >= ema_trend - atr * 0.25)

    return {
        "price": price,
        "open": f("open"),
        "high": f("high"),
        "low": f("low"),
        "ema_fast": f("ema_fast"),
        "ema_slow": f("ema_slow"),
        "ema_trend": f("ema_trend"),
        "ema_long": f("ema_long"),
        "fib_bull_zone": float(fib_bull_zone),
        "fib_bear_zone": float(fib_bear_zone),
        "near_support": float(near_support),
        "near_resistance": float(near_resistance),
        "at_bull_level": float(at_bull_level),
        "at_bear_level": float(at_bear_level),
        "pattern_code": float(pattern_code),
        "pattern_dir": float(pattern_dir),
        "vol_ratio": float(vol_ratio),
        "bull_div": float(bull_div),
        "bear_div": float(bear_div),
        "pullback_tag": float(pullback_tag),
        "macd": f("macd"),
        "macd_signal": f("macd_signal"),
        "macd_hist": f("macd_hist"),
        "macd_hist_prev": float(prev["macd_hist"]) if pd.notna(prev["macd_hist"]) else 0.0,
        "rsi": f("rsi"),
        "stoch_k": f("stoch_k"),
        "stoch_d": f("stoch_d"),
        "bb_high": f("bb_high"),
        "bb_mid": f("bb_mid"),
        "bb_low": f("bb_low"),
        "bb_pct": f("bb_pct"),
        "atr": f("atr"),
        "adx": f("adx"),
        "adx_pos": f("adx_pos"),
        "adx_neg": f("adx_neg"),
        "swing_high": f("swing_high"),
        "swing_low": f("swing_low"),
        "ema_fast_prev": float(prev["ema_fast"]) if pd.notna(prev["ema_fast"]) else f("ema_fast"),
        "ema_slow_prev": float(prev["ema_slow"]) if pd.notna(prev["ema_slow"]) else f("ema_slow"),
    }


def safe_nan(value: float, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    return float(value)
