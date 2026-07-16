# AURUM — XAU/USD Trading Signal Bot

Educational chart-analysis bot for **XAU/USD (Gold)**. It reads live market candles, scores multiple technical indicators, and returns a clear trade suggestion:

1. **Buy / Sell / Wait**
2. **Lot size** (scales with confidence and your risk %)
3. **Take Profit & Stop Loss** (ATR + structure)
4. **Win probability %** (confluence-based — not a guarantee)

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
Get signals as chat messages (Buy/Sell, lot, TP/SL, win %).

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

## What you get

| Output | Meaning |
|--------|---------|
| Side | `BUY`, `SELL`, or `WAIT` when confluence is weak |
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
