#!/usr/bin/env python3
"""CLI for one-shot XAU/USD trading signals."""

from __future__ import annotations

import argparse
import json
import sys

from backend.signal_engine import analyze_xauusd


def main() -> int:
    parser = argparse.ArgumentParser(description="XAU/USD trading signal bot (CLI)")
    parser.add_argument("--interval", default="15m", choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d"])
    parser.add_argument("--balance", type=float, default=1000.0, help="Account balance in USD")
    parser.add_argument("--risk", type=float, default=2.0, help="Max risk percent per trade")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    try:
        signal = analyze_xauusd(
            interval=args.interval,
            account_balance=args.balance,
            risk_percent=args.risk,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    data = signal.to_dict()
    # Keep CLI output compact
    data.pop("candles", None)

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    print("=" * 48)
    print(f"  {data['symbol']}  ·  {data['timeframe']}")
    print("=" * 48)
    print(f"  1) Side          : {data['side']}")
    print(f"  2) Lot size      : {data['lot_size']}")
    print(f"  3) TP / SL       : {data['take_profit']}  /  {data['stop_loss']}")
    print(f"     Distances    : TP ${data['tp_distance']}  |  SL ${data['sl_distance']}  (price $)")
    print(f"  4) Win %         : {data['win_probability']}%  (confidence {data['confidence']}%)")
    print("-" * 48)
    print(f"  Entry           : {data['entry']}")
    print(f"  Risk amount     : ${data['risk_amount']}")
    print(f"  Risk:Reward     : {data['risk_reward']}")
    print(f"  ATR             : {data['atr']}")
    print("-" * 48)
    print("  Why:")
    for reason in data["reasons"]:
        print(f"   • {reason}")
    print("-" * 48)
    print(f"  {data['disclaimer']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
