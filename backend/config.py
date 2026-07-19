"""Configuration for the multi-instrument signal bot."""

from __future__ import annotations

from pydantic_settings import BaseSettings


# Commodities / FX-style (Yahoo for oil; gold live via Binance PAXG)
_COMMODITIES: dict[str, dict[str, object]] = {
    "XAUUSD": {
        "symbol": "GC=F",
        "display_symbol": "XAU/USD",
        "contract_size": 100.0,
        "binance": "PAXGUSDT",
        "category": "metals",
        "name": "Gold",
        "keywords": "gold xau paxg",
    },
    "USOIL": {
        "symbol": "CL=F",
        "display_symbol": "USOIL",
        "contract_size": 1000.0,
        "binance": None,
        "category": "energy",
        "name": "Crude Oil WTI",
        "keywords": "oil wti crude usoil",
    },
}

# Popular Binance USDT pairs — chart + signals use the same Binance book.
_CRYPTO_PAIRS: list[tuple[str, str, str, str]] = [
    # key, binance_symbol, display base, full name
    ("BTCUSD", "BTCUSDT", "BTC", "Bitcoin"),
    ("ETHUSD", "ETHUSDT", "ETH", "Ethereum"),
    ("BNBUSD", "BNBUSDT", "BNB", "BNB"),
    ("SOLUSD", "SOLUSDT", "SOL", "Solana"),
    ("XRPUSD", "XRPUSDT", "XRP", "XRP"),
    ("ADAUSD", "ADAUSDT", "ADA", "Cardano"),
    ("DOGEUSD", "DOGEUSDT", "DOGE", "Dogecoin"),
    ("DOTUSD", "DOTUSDT", "DOT", "Polkadot"),
    ("AVAXUSD", "AVAXUSDT", "AVAX", "Avalanche"),
    ("LINKUSD", "LINKUSDT", "LINK", "Chainlink"),
    ("POLUSD", "POLUSDT", "POL", "Polygon"),
    ("LTCUSD", "LTCUSDT", "LTC", "Litecoin"),
    ("ATOMUSD", "ATOMUSDT", "ATOM", "Cosmos"),
    ("UNIUSD", "UNIUSDT", "UNI", "Uniswap"),
    ("APTUSD", "APTUSDT", "APT", "Aptos"),
    ("ARBUSD", "ARBUSDT", "ARB", "Arbitrum"),
    ("OPUSD", "OPUSDT", "OP", "Optimism"),
    ("SUIUSD", "SUIUSDT", "SUI", "Sui"),
    ("NEARUSD", "NEARUSDT", "NEAR", "NEAR Protocol"),
    ("FILUSD", "FILUSDT", "FIL", "Filecoin"),
    ("ICPUSD", "ICPUSDT", "ICP", "Internet Computer"),
    ("AAVEUSD", "AAVEUSDT", "AAVE", "Aave"),
    ("TRXUSD", "TRXUSDT", "TRX", "TRON"),
    ("TONUSD", "TONUSDT", "TON", "Toncoin"),
    ("INJUSD", "INJUSDT", "INJ", "Injective"),
    ("SEIUSD", "SEIUSDT", "SEI", "Sei"),
    ("RENDERUSD", "RENDERUSDT", "RENDER", "Render"),
    ("PEPEUSD", "PEPEUSDT", "PEPE", "Pepe"),
    ("SHIBUSD", "SHIBUSDT", "SHIB", "Shiba Inu"),
    ("WIFUSD", "WIFUSDT", "WIF", "dogwifhat"),
    ("FETUSD", "FETUSDT", "FET", "Artificial Superintelligence"),
    ("TAOUSD", "TAOUSDT", "TAO", "Bittensor"),
]


def _build_instruments() -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = dict(_COMMODITIES)
    for key, bn, base, name in _CRYPTO_PAIRS:
        out[key] = {
            "symbol": bn,  # primary OHLCV source = Binance
            "display_symbol": f"{base}/USDT",
            "contract_size": 1.0,
            "binance": bn,
            "category": "crypto",
            "name": name,
            "keywords": f"{name} {base} {bn} {key}".lower(),
        }
    return out


INSTRUMENTS: dict[str, dict[str, object]] = _build_instruments()
DEFAULT_INSTRUMENT = "BTCUSD"


def _normalize_instrument_key(key: str | None) -> str:
    """ETHUSDT / ethusd → ETHUSD."""
    k = (key or DEFAULT_INSTRUMENT).upper().strip()
    if k.endswith("USDT") and len(k) > 4:
        return f"{k[:-4]}USD"
    return k


def get_instrument(key: str | None) -> dict[str, object]:
    """Resolve instrument config (static catalog or any Binance USDT pair)."""
    k = _normalize_instrument_key(key)
    if k in INSTRUMENTS:
        return INSTRUMENTS[k]
    raw = (key or "").upper().strip()
    if raw in INSTRUMENTS:
        return INSTRUMENTS[raw]

    try:
        from backend.live_feed import fetch_binance_usdt_markets

        for m in fetch_binance_usdt_markets():
            if m["key"] == k or m["binance"] == raw or m["binance"] == k:
                return {
                    "symbol": m["binance"],
                    "display_symbol": m["label"],
                    "contract_size": 1.0,
                    "binance": m["binance"],
                    "category": "crypto",
                    "name": m["name"],
                    "keywords": m["keywords"],
                }
    except Exception:  # noqa: BLE001
        pass
    return INSTRUMENTS[DEFAULT_INSTRUMENT]


def binance_symbol(key: str | None) -> str | None:
    """Return Binance pair for live chart / aligned analysis, if any."""
    inst = get_instrument(key)
    bn = inst.get("binance")
    return str(bn) if bn else None


def is_known_instrument(key: str | None) -> bool:
    if not key:
        return False
    k = _normalize_instrument_key(key)
    if k in INSTRUMENTS or key.upper() in INSTRUMENTS:
        return True
    try:
        from backend.live_feed import binance_pair_for_key

        return binance_pair_for_key(k) is not None or binance_pair_for_key(key.upper()) is not None
    except Exception:  # noqa: BLE001
        return False


class Settings(BaseSettings):
    symbol: str = "BTCUSDT"
    display_symbol: str = "BTC/USDT"

    default_interval: str = "15m"
    default_period: str = "5d"
    lookback_bars: int = 200

    account_balance: float = 1000.0
    max_risk_percent: float = 1.0
    min_lot: float = 0.01
    max_lot: float = 1.0
    lot_step: float = 0.01

    contract_size: float = 1.0
    point_value_per_lot: float = 1.0

    sl_atr_mult: float = 1.25
    tp_atr_mult: float = 3.0
    max_sl_atr_mult: float = 1.5
    min_rr: float = 2.0

    min_confidence_to_trade: float = 55.0
    high_confidence: float = 75.0

    model_config = {"env_prefix": "XAU_"}


settings = Settings()
