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

    return data


def latest_snapshot(df: pd.DataFrame) -> dict:
    """Return the most recent indicator values as a plain dict."""
    row = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else row

    def f(key: str) -> float:
        val = row[key]
        return float(val) if pd.notna(val) else float("nan")

    return {
        "price": f("close"),
        "open": f("open"),
        "high": f("high"),
        "low": f("low"),
        "ema_fast": f("ema_fast"),
        "ema_slow": f("ema_slow"),
        "ema_trend": f("ema_trend"),
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
