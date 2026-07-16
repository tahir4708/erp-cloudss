"""FastAPI app for the XAU/USD trading signal bot."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import settings
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


class AnalyzeRequest(BaseModel):
    interval: str = Field(default="15m", description="Candle timeframe")
    account_balance: float = Field(default=1000.0, gt=0, description="Account balance in USD")
    risk_percent: float = Field(default=2.0, gt=0, le=5, description="Max risk % per trade")
    mode: str = Field(default="indicators", pattern="^(indicators|candles)$")


@app.get("/api/health")
def health():
    return {"status": "ok", "symbol": settings.display_symbol}


@app.get("/api/signal")
def get_signal(
    interval: str = Query(default="15m", pattern="^(1m|5m|15m|30m|1h|4h|1d)$"),
    account_balance: float = Query(default=1000.0, gt=0),
    risk_percent: float = Query(default=2.0, gt=0, le=5),
    mode: str = Query(default="indicators", pattern="^(indicators|candles)$"),
):
    try:
        signal = analyze_xauusd(
            interval=interval,
            account_balance=account_balance,
            risk_percent=risk_percent,
            mode=mode,  # type: ignore[arg-type]
        )
        payload = signal.to_dict()
        try:
            if mode == "indicators":
                payload["recent_edge"] = quick_backtest_hint(interval=interval)
            else:
                payload["recent_edge"] = None
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
        mode=body.mode,
    )


@app.get("/")
def index():
    index_path = FRONTEND / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
