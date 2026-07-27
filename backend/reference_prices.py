"""Spot / TradingView-aligned reference prices (Yahoo futures indices)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from backend.data_feed import fetch_ohlcv, YAHOO_CHART, HEADERS as DATA_HEADERS

logger = logging.getLogger(__name__)

# Maps instrument key → Yahoo symbol used on TradingView-style XAU/USD / XAG charts
SPOT_REFERENCE: dict[str, dict[str, str]] = {
    "XAUUSD": {"yahoo": "GC=F", "label": "XAU/USD Spot", "tv_hint": "TradingView GOLD / XAUUSD"},
    "XAGUSD": {"yahoo": "SI=F", "label": "XAG/USD Spot", "tv_hint": "TradingView SILVER / XAGUSD"},
    "BTCUSD": {"yahoo": None, "label": "BTC/USD", "tv_hint": "Use Binance BTCUSDT"},
    "USOIL": {"yahoo": "CL=F", "label": "WTI Oil", "tv_hint": "TradingView USOIL"},
}

_ticker_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_TICKER_TTL_SEC = 8.0


def spot_reference_for(instrument: str) -> dict[str, str] | None:
    key = (instrument or "").upper()
    if key.endswith("USDT") and len(key) > 4:
        key = f"{key[:-4]}USD"
    ref = SPOT_REFERENCE.get(key)
    return dict(ref) if ref else None


def has_spot_reference(instrument: str) -> bool:
    ref = spot_reference_for(instrument)
    return bool(ref and ref.get("yahoo"))


def fetch_spot_ticker(instrument: str) -> dict[str, Any]:
    """Live-ish spot index (Yahoo chart quote — same family as TradingView futures)."""
    key = (instrument or "").upper()
    ref = spot_reference_for(key)
    if not ref or not ref.get("yahoo"):
        raise RuntimeError(f"No spot reference for {instrument}")

    yahoo_sym = ref["yahoo"]
    now = time.time()
    cached = _ticker_cache.get(key)
    if cached and (now - cached[0]) < _TICKER_TTL_SEC:
        return cached[1]

    # Fast path: Yahoo chart meta (regularMarketPrice)
    try:
        with httpx.Client(timeout=8.0, headers=DATA_HEADERS, follow_redirects=True) as client:
            r = client.get(
                YAHOO_CHART.format(symbol=yahoo_sym),
                params={"interval": "1m", "range": "1d"},
            )
            r.raise_for_status()
            meta = (r.json().get("chart") or {}).get("result", [{}])[0].get("meta") or {}
            price = meta.get("regularMarketPrice") or meta.get("previousClose")
            if price is not None:
                payload = {
                    "instrument": key,
                    "symbol": yahoo_sym,
                    "label": ref["label"],
                    "price": round(float(price), 2),
                    "source": "yahoo_spot",
                    "status": "live",
                    "tv_hint": ref.get("tv_hint"),
                }
                _ticker_cache[key] = (now, payload)
                return payload
    except Exception as exc:  # noqa: BLE001
        logger.debug("Yahoo spot ticker meta failed: %s", exc)

    # Fallback: last candle close
    df = fetch_ohlcv(interval="15m", symbol=yahoo_sym, instrument=key)
    price = float(df.iloc[-1]["close"])
    payload = {
        "instrument": key,
        "symbol": yahoo_sym,
        "label": ref["label"],
        "price": round(price, 2),
        "source": "yahoo_spot",
        "status": "delayed",
        "tv_hint": ref.get("tv_hint"),
    }
    _ticker_cache[key] = (now, payload)
    return payload


def fetch_spot_ohlcv(instrument: str, interval: str = "15m", limit: int = 200) -> Any:
    """OHLCV from Yahoo spot/futures index (TradingView-aligned shape)."""
    key = (instrument or "").upper()
    ref = spot_reference_for(key)
    if not ref or not ref.get("yahoo"):
        raise RuntimeError(f"No spot OHLCV reference for {instrument}")
    df = fetch_ohlcv(interval=interval, symbol=ref["yahoo"], instrument=key)
    if len(df) > limit:
        df = df.iloc[-limit:]
    return df
