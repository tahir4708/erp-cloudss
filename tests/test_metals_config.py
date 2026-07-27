"""Tests for Binance gold/silver instrument config."""

from __future__ import annotations

from backend.config import binance_futures_symbol, binance_market_type, binance_symbol, get_instrument
from backend.live_feed import binance_feed_symbol, has_live_feed
from backend.symbol_catalog import parse_symbol_id, search_symbols


def test_gold_paxg_binance_spot():
    inst = get_instrument("XAUUSD")
    assert inst.get("binance") == "PAXGUSDT"
    assert binance_symbol("XAUUSD") == "PAXGUSDT"
    assert binance_market_type("XAUUSD") == "spot"


def test_tether_gold_binance():
    inst = get_instrument("XAUTUSD")
    assert inst.get("binance") == "XAUTUSDT"
    ms = parse_symbol_id("BINANCE:XAUTUSDT")
    assert ms.base_key == "XAUTUSD"


def test_silver_binance_futures():
    inst = get_instrument("XAGUSD")
    assert inst.get("binance_futures") == "XAGUSDT"
    assert binance_futures_symbol("XAGUSD") == "XAGUSDT"
    assert binance_market_type("XAGUSD") == "futures"
    assert has_live_feed("XAGUSD")
    sym, market = binance_feed_symbol("XAGUSD")
    assert sym == "XAGUSDT"
    assert market == "futures"


def test_search_silver_binance():
    rows = search_symbols("binance silver")
    ids = {r["id"] for r in rows}
    assert "BINANCE:XAGUSDT" in ids

