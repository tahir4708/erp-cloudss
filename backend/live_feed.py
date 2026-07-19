"""Low-latency live market data — Binance USDT universe + 24h stats."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "AurumSignalBot/1.0",
    "Accept": "application/json",
}

INTERVAL_TO_BINANCE: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

BINANCE_BASES = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)

# Cached Binance USDT spot markets: [{key, binance, label, name, ...}, ...]
_markets_cache: list[dict[str, Any]] | None = None
_markets_cached_at = 0.0
_MARKETS_TTL_SEC = 3600.0


def _client(timeout: float = 12.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True)


def _key_from_base(base: str) -> str:
    """ETH -> ETHUSD (our instrument key convention)."""
    return f"{base.upper()}USD"


def fetch_binance_usdt_markets(force: bool = False) -> list[dict[str, Any]]:
    """All tradable Binance spot USDT pairs (cached)."""
    global _markets_cache, _markets_cached_at
    now = time.time()
    if (
        not force
        and _markets_cache is not None
        and (now - _markets_cached_at) < _MARKETS_TTL_SEC
    ):
        return _markets_cache

    errors: list[str] = []
    for base_url in BINANCE_BASES:
        try:
            with _client() as client:
                r = client.get(f"{base_url}/api/v3/exchangeInfo")
                r.raise_for_status()
                payload = r.json()
            rows: list[dict[str, Any]] = []
            for sym in payload.get("symbols") or []:
                if sym.get("status") != "TRADING":
                    continue
                if sym.get("quoteAsset") != "USDT":
                    continue
                if not sym.get("isSpotTradingAllowed", True):
                    continue
                base = str(sym.get("baseAsset") or "")
                bn = str(sym.get("symbol") or "")
                if not base or not bn:
                    continue
                key = _key_from_base(base)
                rows.append(
                    {
                        "key": key,
                        "binance": bn,
                        "label": f"{base}/USDT",
                        "name": base,
                        "category": "crypto",
                        "live": True,
                        "keywords": f"{base} {bn} {key} usdt".lower(),
                    }
                )
            rows.sort(key=lambda x: x["name"])
            _markets_cache = rows
            _markets_cached_at = now
            logger.info("Cached %s Binance USDT markets", len(rows))
            return rows
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{base_url}: {exc}")

    if _markets_cache:
        return _markets_cache
    raise RuntimeError("; ".join(errors) or "Could not load Binance markets")


def binance_pair_for_key(instrument: str) -> str | None:
    """Resolve instrument key (ETHUSD / ETHUSDT) to Binance symbol."""
    from backend.config import INSTRUMENTS

    key = (instrument or "").upper()
    if key in INSTRUMENTS and INSTRUMENTS[key].get("binance"):
        return str(INSTRUMENTS[key]["binance"])

    if key.endswith("USDT"):
        return key

    try:
        for m in fetch_binance_usdt_markets():
            if m["key"] == key or m["binance"] == key:
                return str(m["binance"])
    except Exception:  # noqa: BLE001
        pass
    return None


def has_live_feed(instrument: str) -> bool:
    return bool(binance_pair_for_key(instrument))


def fetch_live_ticker(instrument: str) -> dict[str, Any]:
    """Binance last price + today's (24h) change."""
    key = (instrument or "BTCUSD").upper()
    bn = binance_pair_for_key(key)
    if not bn:
        raise RuntimeError(f"No Binance live feed for {key}")

    errors: list[str] = []
    for base in BINANCE_BASES:
        try:
            with _client() as client:
                r = client.get(f"{base}/api/v3/ticker/24hr", params={"symbol": bn})
                r.raise_for_status()
                data = r.json()
            price = float(data["lastPrice"])
            change_pct = float(data["priceChangePercent"])
            change = float(data["priceChange"])
            return {
                "instrument": key,
                "price": price,
                "change": change,
                "change_pct": change_pct,
                "high": float(data.get("highPrice") or 0),
                "low": float(data.get("lowPrice") or 0),
                "source": "binance",
                "symbol": bn,
                "ts": None,
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"binance({base}): {exc}")

    raise RuntimeError("; ".join(errors) or f"Live ticker failed for {key}")


def fetch_live_klines(instrument: str, interval: str = "15m", limit: int = 80) -> list[dict[str, Any]]:
    """OHLCV seed candles from Binance."""
    key = (instrument or "BTCUSD").upper()
    bn = binance_pair_for_key(key)
    if not bn:
        raise RuntimeError(f"No Binance live feed for {key}")

    limit = max(20, min(int(limit), 200))
    bin_iv = INTERVAL_TO_BINANCE.get(interval, "15m")
    errors: list[str] = []

    for base in BINANCE_BASES:
        try:
            with _client() as client:
                r = client.get(
                    f"{base}/api/v3/klines",
                    params={"symbol": bn, "interval": bin_iv, "limit": limit},
                )
                r.raise_for_status()
                rows = r.json()
            out: list[dict[str, Any]] = []
            for k in rows:
                out.append(
                    {
                        "time": int(k[0]) // 1000,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    }
                )
            if out:
                return out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"binance({base}): {exc}")

    raise RuntimeError("; ".join(errors) or f"Live klines failed for {key}")
