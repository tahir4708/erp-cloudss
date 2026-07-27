@echo off
set PY=C:\Users\tahir\AppData\Local\Programs\Python\Python312\python.exe
set REPO=C:\Users\tahir\aurum-signals
set EXNESS_BRIDGE_PORT=8787
cd /d %REPO%
"%PY%" -m pip install MetaTrader5 fastapi uvicorn httpx -q
echo Starting Exness MT5 bridge on port %EXNESS_BRIDGE_PORT%...
"%PY%" exness_bridge.py
