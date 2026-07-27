"""FastAPI app for the multi-instrument signal bot."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.config import DEFAULT_INSTRUMENT, INSTRUMENTS, is_known_instrument, settings
from backend.exness_feed import compare_prices, fetch_exness_quote, supports_exness
from backend.reference_prices import fetch_spot_ticker, has_spot_reference
from backend.market_data import fetch_market_klines, fetch_market_ticker
from backend.signal_engine import analyze_xauusd, quick_backtest_hint
from backend.symbol_catalog import DEFAULT_SYMBOL_ID, is_known_symbol, parse_symbol_id, search_symbols

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="AURUM Signal Desk",
    description="Multi-instrument chart analysis: crypto (Binance) + gold/oil",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_api(request, call_next):
    """Prevent browsers/proxies from serving stale /api responses."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _require_instrument(instrument: str) -> str:
    key = (instrument or DEFAULT_INSTRUMENT).upper()
    if not is_known_instrument(key):
        raise HTTPException(status_code=400, detail=f"Unknown instrument: {instrument}")
    return key


def _require_symbol(symbol_id: str | None, instrument: str | None = None) -> str:
    """Resolve symbol_id from explicit id or legacy instrument key."""
    raw = (symbol_id or "").strip()
    if raw:
        if not is_known_symbol(raw):
            raise HTTPException(status_code=400, detail=f"Unknown symbol: {raw}")
        return parse_symbol_id(raw).id
    key = _require_instrument(instrument or DEFAULT_INSTRUMENT)
    return parse_symbol_id(key).id


class AnalyzeRequest(BaseModel):
    interval: str = Field(default="15m", description="Candle timeframe")
    account_balance: float = Field(default=1000.0, gt=0, description="Account balance in USD")
    risk_percent: float = Field(default=2.0, gt=0, le=5, description="Max risk % per trade")
    instrument: str = Field(default=DEFAULT_INSTRUMENT, description="Legacy instrument key")
    symbol_id: str | None = Field(default=None, description="TradingView-style VENUE:SYMBOL")
    mode: str = Field(default="indicators", pattern="^(indicators|candles)$")
    price_source: str = Field(
        default="chart",
        pattern="^(chart|exness)$",
        description="Entry price: chart feed or Exness broker (Binance/Yahoo charts only)",
    )

    @field_validator("instrument")
    @classmethod
    def _check_instrument(cls, value: str) -> str:
        key = value.upper()
        if not is_known_instrument(key):
            raise ValueError(f"Unknown instrument: {value}")
        return key


@app.get("/api/health")
def health():
    return {"status": "ok", "symbol": settings.display_symbol, "instruments": len(INSTRUMENTS)}


@app.get("/api/symbols")
def symbols(q: str | None = Query(default=None, description="Search Binance, Exness, Yahoo")):
    """TradingView-style catalog: BINANCE:BTCUSDT, EXNESS:BTCUSDm, YAHOO:GC=F, …"""
    rows = search_symbols(q)
    return {"symbols": rows, "count": len(rows), "default": DEFAULT_SYMBOL_ID}


@app.get("/api/instruments")
def instruments(q: str | None = Query(default=None, description="Optional search filter")):
    """Full searchable catalog: commodities + all Binance USDT spot pairs."""
    from backend.live_feed import fetch_binance_usdt_markets

    needle = (q or "").strip().lower()
    by_key: dict[str, dict] = {}

    for key, cfg in INSTRUMENTS.items():
        label = str(cfg["display_symbol"])
        name = str(cfg.get("name") or label)
        category = str(cfg.get("category") or "other")
        keywords = str(cfg.get("keywords") or "")
        binance = cfg.get("binance")
        by_key[key] = {
            "key": key,
            "label": label,
            "name": name,
            "category": category,
            "binance": binance,
            "live": bool(binance),
            "keywords": keywords,
        }

    try:
        for m in fetch_binance_usdt_markets():
            key = str(m["key"])
            if key in by_key:
                # Keep curated name (e.g. Bitcoin) but ensure live flag
                by_key[key]["live"] = True
                by_key[key]["binance"] = by_key[key].get("binance") or m["binance"]
                continue
            by_key[key] = {
                "key": key,
                "label": m["label"],
                "name": m["name"],
                "category": "crypto",
                "binance": m["binance"],
                "live": True,
                "keywords": m.get("keywords") or "",
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance market catalog unavailable: %s", exc)

    rows = []
    for row in by_key.values():
        hay = (
            f"{row['key']} {row['label']} {row['name']} "
            f"{row.get('keywords') or ''} {row.get('binance') or ''}"
        ).lower()
        if needle and needle not in hay:
            continue
        rows.append(row)

    # Metals/energy first, then cryptos A–Z
    rows.sort(
        key=lambda r: (
            0 if r["category"] in ("metals", "energy") else 1,
            r["name"].lower(),
        )
    )
    return {"instruments": rows, "count": len(rows)}


@app.get("/api/signal")
def get_signal(
    interval: str = Query(default="15m", pattern="^(1m|5m|15m|30m|1h|4h|1d)$"),
    account_balance: float = Query(default=1000.0, gt=0),
    risk_percent: float = Query(default=2.0, gt=0, le=5),
    instrument: str = Query(default=DEFAULT_INSTRUMENT),
    symbol_id: str | None = Query(default=None, description="VENUE:SYMBOL e.g. BINANCE:BTCUSDT"),
    mode: str = Query(default="indicators", pattern="^(indicators|candles)$"),
    price_source: str = Query(default="chart", pattern="^(chart|exness)$"),
):
    sid = _require_symbol(symbol_id, instrument)
    ms = parse_symbol_id(sid)
    if price_source == "exness" and ms.venue != "EXNESS" and not supports_exness(ms.base_key):
        raise HTTPException(
            status_code=400,
            detail="Exness entry only for Gold (XAUUSD) and BTC (BTCUSD)",
        )
    try:
        signal = analyze_xauusd(
            interval=interval,
            account_balance=account_balance,
            risk_percent=risk_percent,
            symbol_id=sid,
            mode=mode,  # type: ignore[arg-type]
            price_source=price_source,  # type: ignore[arg-type]
        )
        payload = signal.to_dict()
        if supports_exness(ms.base_key):
            try:
                payload["broker_compare"] = compare_prices(ms.base_key, sid)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Broker compare failed: %s", exc)
                payload["broker_compare"] = None
        if (
            mode != "indicators"
            or os.getenv("DISABLE_BACKTEST_HINT", "").lower() in ("1", "true", "yes")
        ):
            payload["recent_edge"] = None
        else:
            try:
                payload["recent_edge"] = quick_backtest_hint(
                    interval=interval, instrument=ms.base_key
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Backtest hint failed: %s", exc)
                payload["recent_edge"] = None
        return payload
    except Exception as exc:  # noqa: BLE001
        logger.exception("Signal generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/signal")
def post_signal(body: AnalyzeRequest):
    return get_signal(
        interval=body.interval,
        account_balance=body.account_balance,
        risk_percent=body.risk_percent,
        instrument=body.instrument,
        symbol_id=body.symbol_id,
        mode=body.mode,
        price_source=body.price_source,
    )


@app.get("/api/broker/compare")
def broker_compare(
    instrument: str = Query(default="XAUUSD"),
    symbol_id: str | None = Query(default=None, description="Active chart VENUE:SYMBOL"),
):
    """Chart vs Spot/TV reference vs Exness — Gold, Silver, BTC."""
    instrument = _require_instrument(instrument)
    if not supports_exness(instrument):
        raise HTTPException(
            status_code=400,
            detail="Exness compare is available for XAUUSD, XAGUSD, and BTCUSD",
        )
    sid = symbol_id
    if sid and not is_known_symbol(sid):
        sid = None
    try:
        return compare_prices(instrument, sid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/reference/spot")
def reference_spot(instrument: str = Query(default="XAUUSD")):
    """TradingView-aligned spot index (Yahoo GC=F / SI=F)."""
    instrument = _require_instrument(instrument)
    if not has_spot_reference(instrument):
        raise HTTPException(status_code=400, detail=f"No spot reference for {instrument}")
    try:
        return fetch_spot_ticker(instrument)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/broker/exness/quote")
def broker_exness_quote(instrument: str = Query(default="XAUUSD")):
    instrument = _require_instrument(instrument)
    if not supports_exness(instrument):
        raise HTTPException(status_code=400, detail="Exness quote only for XAUUSD and BTCUSD")
    try:
        return fetch_exness_quote(instrument)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/live/ticker")
def live_ticker(
    instrument: str = Query(default=DEFAULT_INSTRUMENT),
    symbol_id: str | None = Query(default=None, description="VENUE:SYMBOL"),
):
    """Fresh last price for the live chart."""
    sid = _require_symbol(symbol_id, instrument)
    try:
        return fetch_market_ticker(sid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live ticker failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/live/klines")
def live_klines(
    instrument: str = Query(default=DEFAULT_INSTRUMENT),
    symbol_id: str | None = Query(default=None, description="VENUE:SYMBOL"),
    interval: str = Query(default="15m", pattern="^(1m|5m|15m|30m|1h|4h|1d)$"),
    limit: int = Query(default=80, ge=20, le=200),
):
    """OHLCV seed candles for the live chart."""
    sid = _require_symbol(symbol_id, instrument)
    try:
        candles = fetch_market_klines(sid, interval=interval, limit=limit)
        ms = parse_symbol_id(sid)
        return {
            "symbol_id": sid,
            "instrument": ms.base_key,
            "venue": ms.venue,
            "interval": interval,
            "candles": candles,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live klines failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/")
def index():
    index_path = FRONTEND / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
