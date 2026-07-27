"""Exness broker prices for Gold & BTC — compare with chart feed and align entry."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Literal

import httpx

from backend.config import get_instrument
from backend.live_feed import fetch_live_ticker, has_live_feed
from backend.reference_prices import fetch_spot_ticker, has_spot_reference

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "AurumSignalBot/1.0",
    "Accept": "application/json",
}

# Exness MT5 symbol names (standard account suffix "m")
EXNESS_SYMBOL_MAP: dict[str, str] = {
    "XAUUSD": "XAUUSDm",
    "XAGUSD": "XAGUSDm",
    "BTCUSD": "BTCUSDm",
}

# Instruments where we show Exness vs reference comparison
EXNESS_SUPPORTED = frozenset(EXNESS_SYMBOL_MAP.keys())

QuoteStatus = Literal["live", "estimated", "unavailable"]

_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_QUOTE_TTL_SEC = 2.0


def supports_exness(instrument: str | None) -> bool:
    key = (instrument or "").upper()
    if key.endswith("USDT") and len(key) > 4:
        key = f"{key[:-4]}USD"
    return key in EXNESS_SUPPORTED


def exness_symbol(instrument: str | None) -> str | None:
    key = (instrument or "").upper()
    if key.endswith("USDT") and len(key) > 4:
        key = f"{key[:-4]}USD"
    return EXNESS_SYMBOL_MAP.get(key)


def _offset_for(instrument: str) -> float:
    """Manual calibration: Exness ≈ reference + offset (set after comparing your terminal)."""
    key = instrument.upper()
    env_key = f"EXNESS_OFFSET_{key}"
    raw = os.getenv(env_key, os.getenv("EXNESS_OFFSET_DEFAULT", "0"))
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _bridge_url() -> str | None:
    url = (os.getenv("EXNESS_BRIDGE_URL") or "").strip().rstrip("/")
    return url or None


def _fetch_bridge_quote(ex_symbol: str) -> dict[str, Any] | None:
    """Read bid/ask from a local bridge (e.g. exness_bridge.py + MetaTrader 5)."""
    base = _bridge_url()
    if not base:
        return None

    paths = [
        f"{base}/quote/{ex_symbol}",
        f"{base}/quotes?symbols={ex_symbol}",
    ]
    with httpx.Client(timeout=4.0, headers=HEADERS, follow_redirects=True) as client:
        for url in paths:
            try:
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
                if "bid" in data and "ask" in data:
                    return data
                if isinstance(data, dict):
                    block = data.get(ex_symbol) or data.get("quotes", {}).get(ex_symbol)
                    if isinstance(block, dict) and "bid" in block:
                        return block
            except Exception as exc:  # noqa: BLE001
                logger.debug("Exness bridge %s failed: %s", url, exc)
    return None


def _estimate_exness_quote(instrument: str, reference_price: float) -> dict[str, Any]:
    offset = _offset_for(instrument)
    mid = reference_price + offset
    # Typical Exness spread hint (display only when estimating)
    spread = max(abs(mid) * 0.00005, 0.05 if instrument == "XAUUSD" else 1.0)
    return {
        "instrument": instrument,
        "symbol": exness_symbol(instrument),
        "bid": round(mid - spread / 2, 2),
        "ask": round(mid + spread / 2, 2),
        "mid": round(mid, 2),
        "source": "exness",
        "status": "estimated",
        "note": (
            "Estimated from spot/TV index + offset. "
            "Run exness_bridge.py on your PC for live Exness prices, "
            "or set EXNESS_OFFSET_XAUUSD / EXNESS_OFFSET_XAGUSD / EXNESS_OFFSET_BTCUSD."
        ),
    }


def fetch_exness_quote(instrument: str) -> dict[str, Any]:
    """Live Exness quote via bridge, else estimated from reference + offset."""
    key = instrument.upper()
    if not supports_exness(key):
        raise RuntimeError(f"Exness quotes not configured for {instrument}")

    now = time.time()
    cached = _quote_cache.get(key)
    if cached and (now - cached[0]) < _QUOTE_TTL_SEC:
        return cached[1]

    ex_sym = exness_symbol(key)
    if not ex_sym:
        raise RuntimeError(f"No Exness symbol for {instrument}")

    bridge = _fetch_bridge_quote(ex_sym)
    if bridge:
        bid = float(bridge["bid"])
        ask = float(bridge["ask"])
        payload = {
            "instrument": key,
            "symbol": ex_sym,
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "mid": round((bid + ask) / 2, 2),
            "source": "exness",
            "status": "live",
            "note": "Live from Exness bridge (MT5)",
        }
        _quote_cache[key] = (now, payload)
        return payload

    ref_price, _ = _reference_price(key)
    payload = _estimate_exness_quote(key, ref_price)
    _quote_cache[key] = (now, payload)
    return payload


def _reference_price(instrument: str) -> tuple[float, str]:
    """Best reference for Exness CFD alignment (spot/TV index preferred over crypto tokens)."""
    key = instrument.upper()
    if has_spot_reference(key):
        try:
            spot = fetch_spot_ticker(key)
            return float(spot["price"]), f"spot:{spot['symbol']}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Spot reference failed for %s: %s", key, exc)
    if has_live_feed(key):
        try:
            t = fetch_live_ticker(key)
            return float(t["price"]), str(t.get("source", "binance"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Binance reference failed for %s: %s", key, exc)
    inst = get_instrument(key)
    from backend.data_feed import fetch_ohlcv

    df = fetch_ohlcv(interval="15m", symbol=str(inst["symbol"]), instrument=key)
    return float(df.iloc[-1]["close"]), "yahoo"


def compare_prices(instrument: str, chart_symbol_id: str | None = None) -> dict[str, Any]:
    """Side-by-side: chart feed, spot/TV reference, and Exness (Gold, Silver, BTC)."""
    key = instrument.upper()
    if not supports_exness(key):
        raise RuntimeError(f"Broker compare only for {', '.join(sorted(EXNESS_SUPPORTED))}")

    chart: dict[str, Any] = {"instrument": key, "status": "unavailable"}
    if chart_symbol_id:
        try:
            from backend.market_data import fetch_market_ticker

            t = fetch_market_ticker(chart_symbol_id)
            chart = {
                "instrument": key,
                "symbol_id": chart_symbol_id,
                "price": round(float(t["price"]), 2),
                "source": t.get("source", "chart"),
                "symbol": t.get("symbol"),
                "label": t.get("label"),
                "change_pct": t.get("change_pct"),
                "status": "live",
            }
        except Exception as exc:  # noqa: BLE001
            chart["error"] = str(exc)

    reference: dict[str, Any] = {"instrument": key, "status": "unavailable"}
    if has_live_feed(key) and not chart.get("price"):
        try:
            t = fetch_live_ticker(key)
            reference = {
                "instrument": key,
                "price": round(float(t["price"]), 2),
                "source": t.get("source", "binance"),
                "symbol": t.get("symbol"),
                "change_pct": t.get("change_pct"),
                "status": "live",
                "label": "Binance default",
            }
        except Exception as exc:  # noqa: BLE001
            reference["error"] = str(exc)
    elif chart.get("price"):
        reference = dict(chart)

    spot_ref: dict[str, Any] | None = None
    if has_spot_reference(key):
        try:
            spot = fetch_spot_ticker(key)
            spot_ref = {
                "instrument": key,
                "price": round(float(spot["price"]), 2),
                "source": spot.get("source", "yahoo_spot"),
                "symbol": spot.get("symbol"),
                "label": spot.get("label"),
                "status": spot.get("status", "live"),
                "tv_hint": spot.get("tv_hint"),
            }
        except Exception as exc:  # noqa: BLE001
            spot_ref = {"instrument": key, "status": "unavailable", "error": str(exc)}

    exness = fetch_exness_quote(key)
    ref_mid = (spot_ref or reference).get("price")
    chart_mid = chart.get("price") or reference.get("price")
    ex_mid = exness.get("mid")

    diff_exness_spot: dict[str, Any] | None = None
    if ref_mid is not None and ex_mid is not None:
        delta = round(ex_mid - ref_mid, 2)
        pct = round((delta / ref_mid) * 100, 4) if ref_mid else 0.0
        diff_exness_spot = {"amount": delta, "pct": pct, "label": "Exness vs Spot/TV"}

    diff_chart_spot: dict[str, Any] | None = None
    if chart_mid is not None and spot_ref and spot_ref.get("price") is not None:
        spot_p = float(spot_ref["price"])
        delta = round(chart_mid - spot_p, 2)
        pct = round((delta / spot_p) * 100, 4) if spot_p else 0.0
        diff_chart_spot = {"amount": delta, "pct": pct, "label": "Chart vs Spot/TV"}

    # Legacy field: exness vs primary reference
    diff = diff_exness_spot

    alignment_note = None
    if exness.get("status") == "estimated":
        alignment_note = (
            "Exness price is estimated from spot index + offset. "
            "Run exness_bridge.py for exact Exness terminal prices, "
            "or set EXNESS_OFFSET_XAUUSD / EXNESS_OFFSET_BTCUSD."
        )
    if spot_ref and chart.get("price") and abs(diff_chart_spot.get("amount", 0) or 0) > 2:
        alignment_note = (
            (alignment_note or "")
            + " Chart shows Binance token/futures; Spot/TV shows COMEX index — "
            "they are different products; pick the symbol that matches your broker."
        ).strip()

    return {
        "instrument": key,
        "chart": chart,
        "reference": reference,
        "spot_reference": spot_ref,
        "exness": exness,
        "diff": diff,
        "diff_exness_spot": diff_exness_spot,
        "diff_chart_spot": diff_chart_spot,
        "bridge_configured": bool(_bridge_url()),
        "offsets": {
            "XAUUSD": _offset_for("XAUUSD"),
            "XAGUSD": _offset_for("XAGUSD"),
            "BTCUSD": _offset_for("BTCUSD"),
        },
        "alignment_note": alignment_note,
    }


def exness_entry_price(instrument: str | None, fallback: float) -> tuple[float, dict[str, Any] | None]:
    """Entry at Exness mid when supported; returns (price, broker_meta)."""
    key = (instrument or "").upper()
    if not supports_exness(key):
        return fallback, None
    try:
        q = fetch_exness_quote(key)
        return float(q["mid"]), q
    except Exception:  # noqa: BLE001
        return fallback, None
