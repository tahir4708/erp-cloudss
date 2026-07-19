"""TradingView-style symbol catalog: VENUE:SYMBOL (Binance, Exness, Yahoo)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.config import INSTRUMENTS, _COMMODITIES, get_instrument

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL_ID = "BINANCE:BTCUSDT"

# Exness MT5 CFD symbols (expand as needed)
_EXNESS_MARKETS: list[tuple[str, str, str, str]] = [
    # symbol, display label, name, base_key (for sizing / offsets)
    ("BTCUSDm", "BTC/USD", "Bitcoin", "BTCUSD"),
    ("ETHUSDm", "ETH/USD", "Ethereum", "ETHUSD"),
    ("XAUUSDm", "XAU/USD", "Gold", "XAUUSD"),
    ("SOLUSDm", "SOL/USD", "Solana", "SOLUSD"),
    ("XRPUSDm", "XRP/USD", "XRP", "XRPUSD"),
    ("LTCUSDm", "LTC/USD", "Litecoin", "LTCUSD"),
    ("DOGEUSDm", "DOGE/USD", "Dogecoin", "DOGEUSD"),
    ("ADAUSDm", "ADA/USD", "Cardano", "ADAUSD"),
    ("BNBUSDm", "BNB/USD", "BNB", "BNBUSD"),
    ("AVAXUSDm", "AVAX/USD", "Avalanche", "AVAXUSD"),
    ("LINKUSDm", "LINK/USD", "Chainlink", "LINKUSD"),
    ("DOTUSDm", "DOT/USD", "Polkadot", "DOTUSD"),
]

# Yahoo symbols for commodities without Binance
_YAHOO_MARKETS: list[tuple[str, str, str, str, str]] = [
    # yahoo_symbol, label, name, base_key, category
    ("GC=F", "XAU/USD", "Gold Futures", "XAUUSD", "metals"),
    ("CL=F", "USOIL", "Crude Oil WTI", "USOIL", "energy"),
]


@dataclass(frozen=True)
class MarketSymbol:
    id: str
    venue: str
    symbol: str
    label: str
    name: str
    category: str
    base_key: str
    live: bool
    keywords: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "venue": self.venue,
            "symbol": self.symbol,
            "label": self.label,
            "name": self.name,
            "category": self.category,
            "base_key": self.base_key,
            "live": self.live,
            "keywords": self.keywords,
            "display": f"{self.venue} · {self.label}",
        }


def make_symbol_id(venue: str, symbol: str) -> str:
    return f"{venue.upper()}:{symbol}"


def parse_symbol_id(symbol_id: str | None) -> MarketSymbol:
    """Resolve VENUE:SYMBOL to catalog entry (or build dynamic Binance entry)."""
    raw = (symbol_id or DEFAULT_SYMBOL_ID).strip()
    if ":" not in raw:
        # Legacy instrument key → default Binance
        inst = get_instrument(raw)
        bn = inst.get("binance")
        if bn:
            return parse_symbol_id(make_symbol_id("BINANCE", str(bn)))
        yahoo = inst.get("symbol")
        return parse_symbol_id(make_symbol_id("YAHOO", str(yahoo)))

    venue, symbol = raw.split(":", 1)
    venue = venue.upper()
    symbol = symbol.strip()
    if venue == "EXNESS" and not symbol.upper().endswith("M"):
        symbol = f"{symbol}m"

    catalog = build_symbol_catalog()
    for row in catalog:
        if row.id == f"{venue}:{symbol}" or (row.venue == venue and row.symbol.upper() == symbol.upper()):
            return row

    # Dynamic Binance USDT pair
    if venue == "BINANCE" and symbol.endswith("USDT"):
        base = symbol[:-4]
        return MarketSymbol(
            id=make_symbol_id("BINANCE", symbol),
            venue="BINANCE",
            symbol=symbol.upper(),
            label=f"{base}/USDT",
            name=base,
            category="crypto",
            base_key=f"{base}USD",
            live=True,
            keywords=f"{base} {symbol} binance usdt".lower(),
        )

    # Dynamic Exness *m symbol
    if venue == "EXNESS" and symbol.upper().endswith("M"):
        base = symbol.upper().replace("USDm", "").replace("USDTM", "")
        return MarketSymbol(
            id=make_symbol_id("EXNESS", symbol.upper()),
            venue="EXNESS",
            symbol=symbol.upper(),
            label=f"{base}/USD",
            name=base,
            category="crypto" if base not in ("XAU",) else "metals",
            base_key=f"{base}USD" if base != "XAU" else "XAUUSD",
            live=True,
            keywords=f"{base} {symbol} exness".lower(),
        )

    raise ValueError(f"Unknown symbol: {symbol_id}")


def build_symbol_catalog() -> list[MarketSymbol]:
    """All markets grouped by venue — TradingView style."""
    rows: dict[str, MarketSymbol] = {}

    # Binance — curated + full USDT universe
    for key, cfg in INSTRUMENTS.items():
        bn = cfg.get("binance")
        if not bn:
            continue
        sym = MarketSymbol(
            id=make_symbol_id("BINANCE", str(bn)),
            venue="BINANCE",
            symbol=str(bn),
            label=str(cfg["display_symbol"]),
            name=str(cfg.get("name") or key),
            category=str(cfg.get("category") or "crypto"),
            base_key=key,
            live=True,
            keywords=f"binance {bn} {key} {cfg.get('keywords', '')}".lower(),
        )
        rows[sym.id] = sym

    try:
        from backend.live_feed import fetch_binance_usdt_markets

        for m in fetch_binance_usdt_markets():
            sid = make_symbol_id("BINANCE", m["binance"])
            if sid in rows:
                continue
            rows[sid] = MarketSymbol(
                id=sid,
                venue="BINANCE",
                symbol=m["binance"],
                label=m["label"],
                name=m["name"],
                category="crypto",
                base_key=m["key"],
                live=True,
                keywords=f"binance {m['binance']} {m.get('keywords', '')}".lower(),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance catalog partial: %s", exc)

    # Exness broker symbols
    for ex_sym, label, name, base_key in _EXNESS_MARKETS:
        sid = make_symbol_id("EXNESS", ex_sym)
        rows[sid] = MarketSymbol(
            id=sid,
            venue="EXNESS",
            symbol=ex_sym,
            label=label,
            name=name,
            category="metals" if base_key == "XAUUSD" else "crypto",
            base_key=base_key,
            live=True,
            keywords=f"exness {ex_sym} {name} {base_key} broker cfd gold xau xauusd exness gold exness xauusd".lower()
            if base_key == "XAUUSD"
            else f"exness {ex_sym} {name} {base_key} broker cfd".lower(),
        )

    # Yahoo commodities
    for yahoo_sym, label, name, base_key, category in _YAHOO_MARKETS:
        sid = make_symbol_id("YAHOO", yahoo_sym)
        rows[sid] = MarketSymbol(
            id=sid,
            venue="YAHOO",
            symbol=yahoo_sym,
            label=label,
            name=name,
            category=category,
            base_key=base_key,
            live=False,
            keywords=f"yahoo {yahoo_sym} {name} {base_key}".lower(),
        )

    # Sort: venue order BINANCE, EXNESS, YAHOO then name
    venue_order = {"BINANCE": 0, "EXNESS": 1, "YAHOO": 2}
    return sorted(
        rows.values(),
        key=lambda r: (venue_order.get(r.venue, 9), r.category not in ("metals", "energy"), r.name.lower()),
    )


def search_symbols(query: str | None = None, limit: int = 120) -> list[dict[str, Any]]:
    catalog = build_symbol_catalog()
    needle = (query or "").strip().lower()
    popular = {
        "BINANCE:BTCUSDT",
        "EXNESS:BTCUSDm",
        "BINANCE:ETHUSDT",
        "EXNESS:ETHUSDm",
        "BINANCE:PAXGUSDT",
        "EXNESS:XAUUSDm",
        "YAHOO:GC=F",
    }
    if not needle:
        head = [r for r in catalog if r.id in popular]
        rest = [r for r in catalog if r.id not in popular][: max(0, limit - len(head))]
        return [r.to_dict() for r in head + rest]

    terms = [t for t in needle.split() if t]
    out: list[MarketSymbol] = []
    # Prefer Exness gold when user searches gold/xau without a venue
    gold_bias = any(t in ("gold", "xau", "xauusd", "xauusdm") for t in terms) and not any(
        t in ("binance", "yahoo") for t in terms
    )

    for row in catalog:
        hay = f"{row.id} {row.venue} {row.symbol} {row.label} {row.name} {row.keywords}".lower()
        if terms and not all(term in hay for term in terms):
            continue
        out.append(row)

    if gold_bias:
        out.sort(
            key=lambda r: (
                0 if r.id == "EXNESS:XAUUSDm" else 1,
                0 if r.venue == "EXNESS" and r.base_key == "XAUUSD" else 2,
                0 if r.base_key == "XAUUSD" else 3,
                r.name.lower(),
            )
        )
    else:
        out.sort(key=lambda r: (r.venue != "EXNESS", r.name.lower()))

    return [r.to_dict() for r in out[:limit]]


def is_known_symbol(symbol_id: str | None) -> bool:
    try:
        parse_symbol_id(symbol_id)
        return True
    except ValueError:
        return False
