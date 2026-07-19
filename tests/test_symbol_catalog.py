"""Tests for TradingView-style symbol catalog."""

from __future__ import annotations

import pytest

from backend.symbol_catalog import (
    DEFAULT_SYMBOL_ID,
    build_symbol_catalog,
    parse_symbol_id,
    search_symbols,
)


def test_default_symbol():
    ms = parse_symbol_id(None)
    assert ms.id == DEFAULT_SYMBOL_ID
    assert ms.venue == "BINANCE"
    assert ms.symbol == "BTCUSDT"


def test_legacy_instrument_maps_to_binance():
    ms = parse_symbol_id("BTCUSD")
    assert ms.venue == "BINANCE"
    assert ms.symbol == "BTCUSDT"


def test_exness_symbol():
    ms = parse_symbol_id("EXNESS:XAUUSDm")
    assert ms.venue == "EXNESS"
    assert ms.symbol == "XAUUSDm"
    assert ms.base_key == "XAUUSD"


def test_yahoo_symbol():
    ms = parse_symbol_id("YAHOO:GC=F")
    assert ms.venue == "YAHOO"
    assert ms.base_key == "XAUUSD"


def test_catalog_has_multiple_venues():
    catalog = build_symbol_catalog()
    venues = {r.venue for r in catalog}
    assert "BINANCE" in venues
    assert "EXNESS" in venues
    assert "YAHOO" in venues


def test_search_btc_returns_binance_and_exness():
    rows = search_symbols("btc")
    ids = {r["id"] for r in rows}
    assert "BINANCE:BTCUSDT" in ids
    assert "EXNESS:BTCUSDm" in ids


def test_unknown_symbol_raises():
    with pytest.raises(ValueError):
        parse_symbol_id("FAKE:NOTREAL")
