"""Tests for Exness broker price compare."""

from __future__ import annotations

from unittest.mock import patch

from backend.exness_feed import (
    compare_prices,
    exness_symbol,
    fetch_exness_quote,
    supports_exness,
)


def test_supports_gold_and_btc():
    assert supports_exness("XAUUSD")
    assert supports_exness("BTCUSD")
    assert not supports_exness("ETHUSD")


def test_exness_symbol_mapping():
    assert exness_symbol("XAUUSD") == "XAUUSDm"
    assert exness_symbol("BTCUSD") == "BTCUSDm"


@patch("backend.exness_feed.fetch_live_ticker")
def test_estimate_exness_quote(mock_ticker):
    mock_ticker.return_value = {"price": 4000.0, "source": "binance", "symbol": "PAXGUSDT"}
    q = fetch_exness_quote("XAUUSD")
    assert q["symbol"] == "XAUUSDm"
    assert q["status"] == "estimated"
    assert q["mid"] == 4000.0


@patch("backend.exness_feed._fetch_bridge_quote")
@patch("backend.exness_feed.fetch_live_ticker")
def test_compare_with_bridge(mock_ticker, mock_bridge):
    mock_ticker.return_value = {"price": 100000.0, "source": "binance", "symbol": "BTCUSDT"}
    mock_bridge.return_value = {"bid": 99800.0, "ask": 99840.0}
    data = compare_prices("BTCUSD")
    assert data["reference"]["price"] == 100000.0
    assert data["exness"]["status"] == "live"
    assert data["exness"]["mid"] == 99820.0
    assert data["diff"]["amount"] == -180.0
