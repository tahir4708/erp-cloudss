# AURUM on Windows Docker (182.180.149.2)

## URLs

| Service | URL |
|---------|-----|
| **AURUM Signal Desk** | http://182.180.149.2:8050 |
| Health check | http://182.180.149.2:8050/api/health |
| Exness bridge (host) | http://127.0.0.1:8787/health |

## Start / update AURUM (Docker)

```powershell
cd C:\Users\tahir\aurum-signals
git pull origin main
docker compose up -d --build
```

Or run: `deploy\windows-host\start-aurum.ps1`

## Exness live prices (required for exact broker alignment)

MetaTrader 5 with Exness must run on this PC.

1. Install [Exness MetaTrader 5](https://www.exness.com/metatrader-5/) and log in (demo or live).
2. Enable **Algo Trading** in MT5.
3. Double-click `deploy\windows-host\start-exness-bridge.bat` (keep window open).

Docker is already configured with `EXNESS_BRIDGE_URL=http://host.docker.internal:8787`.

## Without MT5 bridge

Prices use Yahoo spot index (TradingView-aligned) + optional offsets:

```powershell
setx EXNESS_OFFSET_XAUUSD "0"
setx EXNESS_OFFSET_XAGUSD "0"
setx EXNESS_OFFSET_BTCUSD "0"
```

Then restart: `docker compose up -d`
