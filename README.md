# AURUM — XAU/USD Trading Signal Bot

Educational chart-analysis bot for **XAU/USD (Gold)**. It reads live market candles, scores multiple technical indicators, and returns a clear trade suggestion:

1. **Buy / Sell / Wait**
2. **Entry point** (price to open the trade)
3. **Lot size** (scales with confidence and your risk %)
4. **Take Profit & Stop Loss** (ATR + structure)
5. **Win probability %** (confluence-based — not a guarantee)

> **Disclaimer:** Signals are for education and decision support only. No signal is 100% accurate. This is not financial advice. Trade at your own risk.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Web UI + API
python run.py
# open http://127.0.0.1:8000

# One-shot CLI
python cli.py --interval 15m --balance 1000 --risk 2
```

## Use on your mobile

You have **3 easy options**:

### Option A — Telegram (best for phone)
Get signals as chat messages (Buy/Sell, entry, lot, TP/SL, win %).

1. In Telegram, open **@BotFather** → `/newbot` → copy the **token**
2. Open your new bot and tap **Start**
3. Get your chat id:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
   ```
   Find `"chat":{"id": 123456789}`
4. On a PC / VPS / always-on machine:
   ```bash
   export TELEGRAM_BOT_TOKEN="123:ABC..."
   export TELEGRAM_CHAT_ID="123456789"
   python telegram_bot.py
   ```
5. On your phone Telegram, tap **`/signal`**

Send one signal and exit:
```bash
python telegram_bot.py --once
```

Auto-send every 30 minutes:
```bash
python telegram_bot.py --auto-minutes 30
```

### Option B — Phone browser (same Wi‑Fi as your PC)
1. Start the web app on your computer: `python run.py`
2. Find your PC’s local IP (example `192.168.1.20`)
3. On your phone browser open: `http://192.168.1.20:8000`
4. Optional: browser menu → **Add to Home Screen** for an app-like icon

### Option C — Host online (open from anywhere)
Deploy this repo (Docker included) to Render / Railway / Fly.io / any VPS, then open the public URL on your phone.

```bash
docker build -t aurum .
docker run -p 8000:8000 aurum
```

## Analysis modes

| Mode | Command / UI | What it uses |
|------|----------------|--------------|
| **Indicators** (default) | `--mode indicators` or `/signal` | EMA, MACD, RSI, Stochastic, Bollinger, ADX |
| **Candle patterns** | `--mode candles` or `/signal_candle` | Engulfing, hammer, doji, stars, inside bar, structure — **no indicators** |

```bash
python cli.py --mode candles --interval 15m
```

## Exness prices (Gold & BTC)

Chart analysis uses **Binance** (BTC, PAXG for gold). Your **Exness** terminal can show slightly different prices.

For **XAUUSD** and **BTCUSD** the UI shows **two prices**:
- **Chart** — Binance feed (used for candles/signals)
- **Exness** — broker bid/ask (XAUUSDm / BTCUSDm)

### Live Exness (recommended for demo trading)
1. On your Windows PC with **MetaTrader 5** logged into Exness:
   ```bash
   pip install MetaTrader5 fastapi uvicorn
   python exness_bridge.py
   ```
2. Point AURUM at your PC:
   ```bash
   export EXNESS_BRIDGE_URL=http://192.168.1.20:8787
   ```

### Quick calibration (no bridge)
Compare Exness vs chart once, then set offset (USD):
```bash
export EXNESS_OFFSET_XAUUSD=-1.50
export EXNESS_OFFSET_BTCUSD=12
```

In the UI, set **Entry price → Exness broker** so Entry / TP / SL match your Exness chart.

## What you get

| Output | Meaning |
|--------|---------|
| Side | `BUY`, `SELL`, or `WAIT` when confluence is weak |
| Entry point | Suggested open price for the trade (current market price) |
| Lot size | Position size from account balance, risk %, SL distance, and confidence |
| TP / SL | ATR-based targets (TP always farther than SL); nearby structure can nudge SL, but never blow it out past 2×ATR |
| Win % | Estimated probability from indicator agreement (capped realistically) |

## Analysis stack

- EMA stack & crossover (9 / 21 / 50)
- MACD histogram & signal
- RSI + Stochastic
- Bollinger Band position
- ADX / DI trend strength
- Swing structure vs mid-range
- ATR for stop distance and risk sizing

Market data is fetched from the Yahoo Finance chart API for gold futures (`GC=F`) as an XAU/USD proxy.

## API

```http
GET /api/signal?interval=15m&account_balance=1000&risk_percent=2
GET /api/health
```

Optional intervals: `5m`, `15m`, `30m`, `1h`, `4h`, `1d`.

## Tests

```bash
pytest -q
```

## Notes

- Lot sizing assumes a standard **100 oz / lot** gold CFD model. Adjust `backend/config.py` if your broker contract differs.
- Higher confidence → larger fraction of your max risk % → larger lot (still capped).
- If indicators disagree, the bot returns **WAIT** instead of forcing a trade.
