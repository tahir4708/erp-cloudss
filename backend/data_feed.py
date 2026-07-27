"""Fetch OHLCV market data — Binance for BTC/gold, Yahoo otherwise."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

from backend.config import binance_futures_symbol, binance_symbol, get_instrument, settings
from backend.live_feed import BINANCE_BASES, BINANCE_FUTURES_BASES, INTERVAL_TO_BINANCE

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


def _fetch_binance_ohlcv(binance_symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Pull OHLCV from Binance so analysis uses the same book as the live chart."""
    bin_iv = INTERVAL_TO_BINANCE.get(interval, interval)
    limit = max(60, min(limit, 500))
    errors: list[str] = []

    for base in BINANCE_BASES:
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
                response = client.get(
                    f"{base}/api/v3/klines",
                    params={"symbol": binance_symbol, "interval": bin_iv, "limit": limit},
                )
                response.raise_for_status()
                rows = response.json()
            if not rows:
                continue
            idx = pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True).tz_convert(None)
            df = pd.DataFrame(
                {
                    "open": [float(r[1]) for r in rows],
                    "high": [float(r[2]) for r in rows],
                    "low": [float(r[3]) for r in rows],
                    "close": [float(r[4]) for r in rows],
                    "volume": [float(r[5]) for r in rows],
                },
                index=idx,
            )
            logger.info("Fetched %s Binance bars for %s (%s)", len(df), binance_symbol, bin_iv)
            return df
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{base}: {exc}")

    raise RuntimeError(f"Binance OHLCV failed for {binance_symbol}: {'; '.join(errors)}")


def _fetch_binance_futures_ohlcv(futures_symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Pull OHLCV from Binance USDT-margined futures (e.g. XAGUSDT silver perp)."""
    bin_iv = INTERVAL_TO_BINANCE.get(interval, interval)
    limit = max(60, min(limit, 500))
    errors: list[str] = []

    for base in BINANCE_FUTURES_BASES:
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
                response = client.get(
                    f"{base}/fapi/v1/klines",
                    params={"symbol": futures_symbol, "interval": bin_iv, "limit": limit},
                )
                response.raise_for_status()
                rows = response.json()
            if not rows:
                continue
            idx = pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True).tz_convert(None)
            df = pd.DataFrame(
                {
                    "open": [float(r[1]) for r in rows],
                    "high": [float(r[2]) for r in rows],
                    "low": [float(r[3]) for r in rows],
                    "close": [float(r[4]) for r in rows],
                    "volume": [float(r[5]) for r in rows],
                },
                index=idx,
            )
            logger.info(
                "Fetched %s Binance futures bars for %s (%s)", len(df), futures_symbol, bin_iv
            )
            return df
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{base}: {exc}")

    raise RuntimeError(f"Binance futures OHLCV failed for {futures_symbol}: {'; '.join(errors)}")


def fetch_ohlcv(
    interval: str | None = None,
    period: str | None = None,
    symbol: str | None = None,
    instrument: str | None = None,
) -> pd.DataFrame:
    """Download OHLCV. Prefer Binance when the instrument has a Binance pair."""
    requested_interval = interval or settings.default_interval
    symbol = symbol or settings.symbol

    bn = binance_symbol(instrument) if instrument else None
    bf = binance_futures_symbol(instrument) if instrument else None
    if not bn:
        # Fallback: symbol itself may already be a Binance pair (e.g. ETHUSDT)
        inst = get_instrument(instrument) if instrument else None
        if inst and inst.get("binance"):
            bn = str(inst["binance"])
        elif str(symbol).endswith("USDT"):
            bn = str(symbol).upper()
        elif instrument:
            bn = binance_symbol(instrument)
        if inst and inst.get("binance_futures") and not bf:
            bf = str(inst["binance_futures"])

    if bn:
        try:
            df = _fetch_binance_ohlcv(bn, requested_interval, limit=settings.lookback_bars)
            if len(df) > settings.lookback_bars:
                df = df.iloc[-settings.lookback_bars :]
            return df
        except Exception as binance_exc:  # noqa: BLE001
            logger.warning("Binance spot fetch failed for %s: %s", bn, binance_exc)

    if bf:
        try:
            df = _fetch_binance_futures_ohlcv(bf, requested_interval, limit=settings.lookback_bars)
            if len(df) > settings.lookback_bars:
                df = df.iloc[-settings.lookback_bars :]
            return df
        except Exception as fut_exc:  # noqa: BLE001
            logger.warning("Binance futures fetch failed for %s, falling back: %s", bf, fut_exc)

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
