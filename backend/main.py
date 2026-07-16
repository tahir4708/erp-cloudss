"""FastAPI app for the XAU/USD trading signal bot."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import INSTRUMENTS, settings
from backend.signal_engine import analyze_xauusd, quick_backtest_hint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="XAU/USD Signal Bot",
    description="Chart analysis signals for Gold (XAU/USD): side, entry, lot size, TP/SL, win %",
    version="1.0.0",
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


_INSTRUMENT_PATTERN = "^(" + "|".join(INSTRUMENTS.keys()) + ")$"


class AnalyzeRequest(BaseModel):
    interval: str = Field(default="15m", description="Candle timeframe")
    account_balance: float = Field(default=1000.0, gt=0, description="Account balance in USD")
    risk_percent: float = Field(default=2.0, gt=0, le=5, description="Max risk % per trade")
    instrument: str = Field(default="XAUUSD", description="Instrument key (XAUUSD, USOIL, BTCUSD)")


@app.get("/api/health")
def health():
    return {"status": "ok", "symbol": settings.display_symbol}


@app.get("/api/instruments")
def instruments():
    return {
        "instruments": [
            {"key": key, "label": str(cfg["display_symbol"])}
            for key, cfg in INSTRUMENTS.items()
        ]
    }


@app.get("/api/signal")
def get_signal(
    interval: str = Query(default="15m", pattern="^(1m|5m|15m|30m|1h|4h|1d)$"),
    account_balance: float = Query(default=1000.0, gt=0),
    risk_percent: float = Query(default=2.0, gt=0, le=5),
    instrument: str = Query(default="XAUUSD", pattern=_INSTRUMENT_PATTERN),
):
    try:
        signal = analyze_xauusd(
            interval=interval,
            account_balance=account_balance,
            risk_percent=risk_percent,
            instrument=instrument,
        )
        payload = signal.to_dict()
        # The backtest hint is a heavier loop; it can be disabled (e.g. on
        # serverless platforms with short timeouts) via DISABLE_BACKTEST_HINT.
        if os.getenv("DISABLE_BACKTEST_HINT", "").lower() in ("1", "true", "yes"):
            payload["recent_edge"] = None
        else:
            try:
                payload["recent_edge"] = quick_backtest_hint(
                    interval=interval, instrument=instrument
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
    )


@app.get("/")
def index():
    index_path = FRONTEND / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
