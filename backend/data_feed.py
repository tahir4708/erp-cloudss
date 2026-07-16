"""Fetch OHLCV market data for XAU/USD (gold)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

from backend.config import settings

logger = logging.getLogger(__name__)

# Yahoo chart ranges that work well per interval
INTERVAL_RANGE_MAP = {
    "1m": "1d",
    "5m": "5d",
    "15m": "5d",
    "30m": "1mo",
    "1h": "1mo",
    "4h": "3mo",
    "1d": "1y",
}

# Yahoo does not serve native 4h bars — pull 1h and resample
YAHOO_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "60m",
    "1d": "1d",
}

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AurumSignalBot/1.0)",
    "Accept": "application/json",
}


def _chart_to_df(payload: dict[str, Any]) -> pd.DataFrame:
    result = (payload.get("chart") or {}).get("result")
    if not result:
        err = (payload.get("chart") or {}).get("error")
        raise RuntimeError(f"Yahoo chart error: {err or 'empty result'}")

    block = result[0]
    timestamps = block.get("timestamp") or []
    quote = (block.get("indicators") or {}).get("quote") or [{}]
    q = quote[0]

    if not timestamps or not q:
        raise RuntimeError("Yahoo chart returned no candles")

    df = pd.DataFrame(
        {
            "open": q.get("open"),
            "high": q.get("high"),
            "low": q.get("low"),
            "close": q.get("close"),
            "volume": q.get("volume"),
        },
        index=pd.to_datetime(timestamps, unit="s", utc=True),
    )
    df = df.dropna(subset=["open", "high", "low", "close"])
    df.index = df.index.tz_convert(None)
    df["volume"] = df["volume"].fillna(0.0)
    return df


def fetch_ohlcv(
    interval: str | None = None,
    period: str | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Download OHLCV candles for gold / XAUUSD via Yahoo Finance chart API."""
    requested_interval = interval or settings.default_interval
    symbol = symbol or settings.symbol
    # Accept legacy "period" name from callers; map onto Yahoo "range"
    range_ = period or INTERVAL_RANGE_MAP.get(requested_interval, settings.default_period)
    yahoo_interval = YAHOO_INTERVAL_MAP.get(requested_interval, requested_interval)

    params = {"interval": yahoo_interval, "range": range_}
    url = YAHOO_CHART.format(symbol=symbol)

    try:
        with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            df = _chart_to_df(response.json())
    except Exception as primary_exc:  # noqa: BLE001
        logger.warning(
            "Primary fetch failed for %s %s/%s: %s",
            symbol,
            range_,
            yahoo_interval,
            primary_exc,
        )
        # Fallback: daily candles
        try:
            with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as client:
                response = client.get(
                    YAHOO_CHART.format(symbol=symbol),
                    params={"interval": "1d", "range": "1y"},
                )
                response.raise_for_status()
                df = _chart_to_df(response.json())
                requested_interval = "1d"
        except Exception as secondary_exc:  # noqa: BLE001
            raise RuntimeError(
                f"Could not fetch market data for {symbol}. "
                "Check your network connection or try again later."
            ) from secondary_exc

    if df.empty:
        raise RuntimeError(
            f"Could not fetch market data for {symbol}. "
            "Check your network connection or try again later."
        )

    if requested_interval == "4h":
        df = (
            df.resample("4h")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )

    if len(df) > settings.lookback_bars:
        df = df.iloc[-settings.lookback_bars :]

    logger.info("Fetched %s bars for %s (%s)", len(df), symbol, requested_interval)
    return df


def candles_to_list(df: pd.DataFrame, limit: int = 80) -> list[dict[str, Any]]:
    """Serialize recent candles for the chart UI."""
    tail = df.tail(limit)
    out: list[dict[str, Any]] = []
    for ts, row in tail.iterrows():
        out.append(
            {
                "time": ts.isoformat(),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": float(row["volume"]) if pd.notna(row["volume"]) else 0.0,
            }
        )
    return out
