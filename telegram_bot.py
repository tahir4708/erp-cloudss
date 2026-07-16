#!/usr/bin/env python3
"""Send XAU/USD signals to your phone via Telegram.

Setup:
  1. Open Telegram → search @BotFather → /newbot → copy the token
  2. Message your new bot once (press Start)
  3. Get your chat id:
       curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
     (look for "chat":{"id": 123456789})
  4. Export env vars and run:

       export TELEGRAM_BOT_TOKEN="123:ABC..."
       export TELEGRAM_CHAT_ID="123456789"
       python telegram_bot.py

On your phone, open Telegram and tap:
  /signal   → fresh XAU/USD signal
  /start    → help
"""

from __future__ import annotations

import argparse
import logging
import os
import time

import httpx

from backend.signal_engine import analyze_xauusd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("aurum-telegram")

API = "https://api.telegram.org/bot{token}/{method}"


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing {name}. Set it first, e.g.\n"
            f'  export {name}="..."\n'
            "See telegram_bot.py docstring for setup steps."
        )
    return value


def tg_call(token: str, method: str, **params):
    url = API.format(token=token, method=method)
    with httpx.Client(timeout=45.0) as client:
        response = client.post(url, json=params)
        response.raise_for_status()
        payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload["result"]


def format_signal(interval: str, balance: float, risk: float) -> str:
    s = analyze_xauusd(interval=interval, account_balance=balance, risk_percent=risk)
    d = s.to_dict()
    arrow = {"BUY": "BUY", "SELL": "SELL", "WAIT": "WAIT"}.get(d["side"], d["side"])
    lines = [
        f"AURUM · {d['symbol']} · {d['timeframe']}",
        "",
        f"1) Side     : {arrow}",
        f"2) Lot size : {d['lot_size']}",
        f"3) Entry    : {d['entry']}",
        f"   TP       : {d['take_profit']}  (distance ${d['tp_distance']})",
        f"   SL       : {d['stop_loss']}  (distance ${d['sl_distance']})",
        f"4) Win %    : {d['win_probability']}%  (confidence {d['confidence']}%)",
        "",
        f"R:R {d['risk_reward']} · Risk ~ ${d['risk_amount']} · ATR {d['atr']}",
        "",
        "Why:",
    ]
    for reason in d["reasons"][:6]:
        lines.append(f"* {reason}")
    lines.append("")
    lines.append(d["disclaimer"])
    return "\n".join(lines)


def send_message(token: str, chat_id: str, text: str) -> None:
    # Telegram message limit ~4096 chars
    tg_call(token, "sendMessage", chat_id=chat_id, text=text[:4000])


def handle_updates(
    token: str,
    chat_id: str,
    interval: str,
    balance: float,
    risk: float,
    offset: int,
) -> int:
    updates = tg_call(
        token,
        "getUpdates",
        offset=offset,
        timeout=25,
        allowed_updates=["message"],
    )
    for update in updates:
        offset = update["update_id"] + 1
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        from_chat = str((message.get("chat") or {}).get("id", ""))
        if from_chat != str(chat_id):
            # Ignore other chats for safety
            continue
        cmd = text.split()[0].split("@")[0].lower() if text else ""
        if cmd in {"/start", "/help"}:
            send_message(
                token,
                chat_id,
                "AURUM XAU/USD signal bot\n\n"
                "/signal — analyze gold now\n"
                "/help — this message\n\n"
                "Educational only — not financial advice.",
            )
        elif cmd == "/signal":
            send_message(token, chat_id, "Analyzing XAU/USD…")
            try:
                send_message(token, chat_id, format_signal(interval, balance, risk))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Signal failed")
                send_message(token, chat_id, f"Signal error: {exc}")
    return offset


def main() -> int:
    parser = argparse.ArgumentParser(description="AURUM Telegram mobile signal bot")
    parser.add_argument("--interval", default=os.environ.get("XAU_INTERVAL", "15m"))
    parser.add_argument("--balance", type=float, default=float(os.environ.get("XAU_BALANCE", "1000")))
    parser.add_argument("--risk", type=float, default=float(os.environ.get("XAU_RISK", "2")))
    parser.add_argument(
        "--auto-minutes",
        type=int,
        default=int(os.environ.get("XAU_AUTO_MINUTES", "0")),
        help="If > 0, also auto-send a signal every N minutes",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Send one signal now and exit (no polling)",
    )
    args = parser.parse_args()

    token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")

    if args.once:
        send_message(token, chat_id, format_signal(args.interval, args.balance, args.risk))
        print("Sent one signal to Telegram.")
        return 0

    # Warm greeting
    send_message(
        token,
        chat_id,
        "AURUM is online on your phone.\nTap /signal anytime for XAU/USD.",
    )
    logger.info("Telegram bot running. Open Telegram on your phone and tap /signal")

    offset = 0
    last_auto = 0.0
    while True:
        try:
            offset = handle_updates(
                token, chat_id, args.interval, args.balance, args.risk, offset
            )
            if args.auto_minutes > 0 and time.time() - last_auto >= args.auto_minutes * 60:
                send_message(token, chat_id, format_signal(args.interval, args.balance, args.risk))
                last_auto = time.time()
        except httpx.HTTPError as exc:
            logger.warning("Telegram network issue: %s", exc)
            time.sleep(3)
        except Exception:  # noqa: BLE001
            logger.exception("Loop error")
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
