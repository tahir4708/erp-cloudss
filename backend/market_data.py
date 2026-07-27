"""Venue-routed market data — Binance, Exness, Yahoo."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backend.config import binance_symbol, get_instrument, settings
from backend.data_feed import _fetch_binance_futures_ohlcv, _fetch_binance_ohlcv, fetch_ohlcv as _legacy_fetch
from backend.exness_feed import _bridge_url, _fetch_bridge_quote, fetch_exness_quote
from backend.live_feed import fetch_live_ticker
from backend.symbol_catalog import MarketSymbol, parse_symbol_id

logger = logging.getLogger(__name__)

import httpx

HEADERS = {
    "User-Agent": "AurumSignalBot/1.0",
    "Accept": "application/json",
}


def _reference_binance_for(ms: MarketSymbol) -> str | None:
    inst = get_instrument(ms.base_key)
    bn = inst.get("binance")
    return str(bn) if bn else None


def _fetch_exness_klines_bridge(ex_symbol: str, interval: str, limit: int) -> list[dict] | None:
    base = _bridge_url()
    if not base:
        return None
    url = f"{base}/klines/{ex_symbol}"
    try:
        with httpx.Client(timeout=12.0, headers=HEADERS) as client:
            r = client.get(url, params={"interval": interval, "limit": limit})
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "candles" in data:
                return data["candles"]
            if isinstance(data, list):
                return data
    except Exception as exc:  # noqa: BLE001
        logger.debug("Exness bridge klines failed: %s", exc)
    return None


def _scale_df(df: pd.DataFrame, ratio: float) -> pd.DataFrame:
    if abs(ratio - 1.0) < 1e-9:
        return df
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col] * ratio
    return out


def _fetch_exness_ohlcv(ms: MarketSymbol, interval: str, limit: int) -> pd.DataFrame:
    """Exness candles via MT5 bridge, else scaled from Binance reference."""
    bridge_rows = _fetch_exness_klines_bridge(ms.symbol, interval, limit)
    if bridge_rows:
        idx = pd.to_datetime([int(c["time"]) for c in bridge_rows], unit="s", utc=True).tz_convert(None)
        return pd.DataFrame(
            {
                "open": [float(c["open"]) for c in bridge_rows],
                "high": [float(c["high"]) for c in bridge_rows],
                "low": [float(c["low"]) for c in bridge_rows],
                "close": [float(c["close"]) for c in bridge_rows],
                "volume": [float(c.get("volume") or 0) for c in bridge_rows],
            },
            index=idx,
        )

    ref_bn = _reference_binance_for(ms)
    if not ref_bn:
        raise RuntimeError(f"No reference feed to estimate Exness chart for {ms.symbol}")

    df = _fetch_binance_ohlcv(ref_bn, interval, limit=limit)
    try:
        ex_mid = float(fetch_exness_quote(ms.base_key)["mid"])
        from backend.live_feed import fetch_live_ticker

        ref_mid = float(fetch_live_ticker(ms.base_key)["price"])
        ratio = ex_mid / ref_mid if ref_mid else 1.0
    except Exception:  # noqa: BLE001
        ratio = 1.0
        logger.warning("Using unscaled Exness proxy for %s", ms.symbol)

    return _scale_df(df, ratio)


def fetch_market_ohlcv(symbol_id: str, interval: str | None = None) -> pd.DataFrame:
    """OHLCV for a catalog symbol id (VENUE:SYMBOL)."""
    ms = parse_symbol_id(symbol_id)
    interval = interval or settings.default_interval
    limit = settings.lookback_bars

    if ms.venue == "BINANCE":
        inst = get_instrument(ms.base_key)
        bf = inst.get("binance_futures")
        if bf and ms.symbol.upper() == str(bf).upper():
            df = _fetch_binance_futures_ohlcv(ms.symbol, interval, limit=limit)
        else:
            df = _fetch_binance_ohlcv(ms.symbol, interval, limit=limit)
    elif ms.venue == "EXNESS":
        df = _fetch_exness_ohlcv(ms, interval, limit)
    elif ms.venue == "YAHOO":
        df = _legacy_fetch(interval=interval, symbol=ms.symbol, instrument=ms.base_key)
    else:
        raise RuntimeError(f"Unsupported venue: {ms.venue}")

    if interval == "4h" and ms.venue != "YAHOO":
        df = (
            df.resample("4h")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
        )

    if len(df) > settings.lookback_bars:
        df = df.iloc[-settings.lookback_bars :]
    return df


def fetch_market_ticker(symbol_id: str) -> dict[str, Any]:
    """Last price for symbol id."""
    ms = parse_symbol_id(symbol_id)
    if ms.venue == "BINANCE":
        from backend.live_feed import _fetch_futures_ticker, _fetch_spot_ticker

        inst = get_instrument(ms.base_key)
        bf = inst.get("binance_futures")
        is_futures = bf and ms.symbol.upper() == str(bf).upper()
        try:
            tick = _fetch_futures_ticker(ms.symbol) if is_futures else _fetch_spot_ticker(ms.symbol)
        except Exception:
            t = fetch_live_ticker(ms.base_key)
            return {
                "symbol_id": ms.id,
                "venue": ms.venue,
                "symbol": ms.symbol,
                "label": ms.label,
                "price": t["price"],
                "change_pct": t.get("change_pct"),
                "source": t.get("source", "binance"),
            }
        return {
            "symbol_id": ms.id,
            "venue": ms.venue,
            "symbol": ms.symbol,
            "label": ms.label,
            "price": tick["price"],
            "change_pct": tick.get("change_pct"),
            "source": tick["source"],
            "market": "futures" if is_futures else "spot",
        }
    if ms.venue == "EXNESS":
        q = fetch_exness_quote(ms.base_key)
        return {
            "symbol_id": ms.id,
            "venue": ms.venue,
            "symbol": ms.symbol,
            "label": ms.label,
            "price": q["mid"],
            "bid": q.get("bid"),
            "ask": q.get("ask"),
            "status": q.get("status"),
            "source": "exness",
        }
    # Yahoo — last close from short history
    df = fetch_market_ohlcv(ms.id, "15m")
    price = float(df.iloc[-1]["close"])
    return {
        "symbol_id": ms.id,
        "venue": ms.venue,
        "symbol": ms.symbol,
        "label": ms.label,
        "price": price,
        "source": "yahoo",
    }


def fetch_market_klines(symbol_id: str, interval: str = "15m", limit: int = 80) -> list[dict[str, Any]]:
    """Chart seed candles."""
    ms = parse_symbol_id(symbol_id)
    df = fetch_market_ohlcv(symbol_id, interval)
    tail = df.tail(limit)
    out: list[dict[str, Any]] = []
    for ts, row in tail.iterrows():
        out.append(
            {
                "time": int(pd.Timestamp(ts).timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if pd.notna(row["volume"]) else 0.0,
            }
        )
    return out
