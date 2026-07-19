#!/usr/bin/env python3
"""Local Exness price bridge — run on your PC with MetaTrader 5 (Exness account).

Exness does not offer a free public price API. This tiny server reads bid/ask
from MT5 (connected to your Exness demo/live) and exposes them to AURUM.

Setup (Windows recommended — MT5 + MetaTrader5 package):
  pip install MetaTrader5 fastapi uvicorn
  # Open MetaTrader 5, log in to Exness, enable algo trading
  export EXNESS_BRIDGE_PORT=8787
  python exness_bridge.py

On the machine running AURUM:
  export EXNESS_BRIDGE_URL=http://YOUR_PC_IP:8787

Then Gold/BTC will show live Exness prices next to the chart feed.
"""

from __future__ import annotations

import os

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # type: ignore

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Exness MT5 Bridge", version="1.0.0")

SYMBOLS = ("XAUUSDm", "BTCUSDm")


def _ensure_mt5() -> None:
    if mt5 is None:
        raise HTTPException(
            status_code=503,
            detail="Install MetaTrader5: pip install MetaTrader5 (Windows + MT5 terminal)",
        )
    if not mt5.initialize():
        raise HTTPException(status_code=503, detail=f"MT5 init failed: {mt5.last_error()}")


@app.get("/health")
def health():
    return {"status": "ok", "symbols": list(SYMBOLS)}


@app.get("/quote/{symbol}")
def quote(symbol: str):
    sym = symbol.upper()
    if sym not in SYMBOLS and not sym.endswith("M"):
        sym = f"{sym}m" if sym in ("XAUUSD", "BTCUSD") else sym
    _ensure_mt5()
    if not mt5.symbol_select(sym, True):
        raise HTTPException(status_code=404, detail=f"Symbol {sym} not found in MT5")
    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        raise HTTPException(status_code=502, detail=f"No tick for {sym}")
    return {
        "symbol": sym,
        "bid": float(tick.bid),
        "ask": float(tick.ask),
        "mid": round((float(tick.bid) + float(tick.ask)) / 2, 2),
        "time": int(tick.time),
    }


@app.get("/quotes")
def quotes(symbols: str = "XAUUSDm,BTCUSDm"):
    _ensure_mt5()
    out = {}
    for raw in symbols.split(","):
        sym = raw.strip().upper()
        if not sym:
            continue
        if not mt5.symbol_select(sym, True):
            continue
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            continue
        out[sym] = {
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "mid": round((float(tick.bid) + float(tick.ask)) / 2, 2),
        }
    return out


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("EXNESS_BRIDGE_PORT", "8787"))
    uvicorn.run(app, host="0.0.0.0", port=port)
