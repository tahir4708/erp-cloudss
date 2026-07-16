"""Configuration for the XAU/USD signal bot."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Yahoo Finance symbol for spot gold / XAUUSD proxy
    symbol: str = "GC=F"
    display_symbol: str = "XAU/USD"

    # Candle history
    default_interval: str = "15m"
    default_period: str = "5d"
    lookback_bars: int = 200

    # Account / risk defaults (user can override via API)
    account_balance: float = 1000.0
    max_risk_percent: float = 2.0  # max % of balance risked per trade
    min_lot: float = 0.01
    max_lot: float = 1.0
    lot_step: float = 0.01

    # XAUUSD contract assumptions (standard retail CFD-style)
    # 1 standard lot ≈ 100 oz; pip/point value approx for gold
    contract_size: float = 100.0  # ounces per lot
    point_value_per_lot: float = 1.0  # $1 per $1 move per 0.01 lot ≈ scale via contract

    # ATR-based SL/TP multipliers
    # SL ≈ 1.5×ATR, TP ≈ 2.5×ATR, always keep TP farther than SL (min R:R)
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    max_sl_atr_mult: float = 2.0  # never let structure blow SL past this
    min_rr: float = 1.8

    # Confidence → lot scaling
    min_confidence_to_trade: float = 55.0
    high_confidence: float = 75.0

    model_config = {"env_prefix": "XAU_"}


settings = Settings()
