"""Tests for spot / TradingView reference prices."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from backend.reference_prices import fetch_spot_ticker, has_spot_reference, spot_reference_for


def test_gold_has_spot_reference():
    assert has_spot_reference("XAUUSD")
    ref = spot_reference_for("XAUUSD")
    assert ref and ref["yahoo"] == "GC=F"


def test_silver_has_spot_reference():
    assert has_spot_reference("XAGUSD")
    ref = spot_reference_for("XAGUSD")
    assert ref and ref["yahoo"] == "SI=F"


@patch("backend.reference_prices.fetch_ohlcv")
def test_fetch_spot_ticker_ohlcv_fallback(mock_ohlcv):
    mock_ohlcv.return_value = pd.DataFrame(
        {"close": [28.5], "open": [28.0], "high": [29.0], "low": [27.5], "volume": [100]},
        index=pd.date_range("2024-01-01", periods=1, freq="15min"),
    )
    from backend.reference_prices import _ticker_cache

    _ticker_cache.clear()
    with patch("httpx.Client", side_effect=RuntimeError("skip yahoo meta")):
        t = fetch_spot_ticker("XAGUSD")
    assert t["price"] == 28.5
    assert t["symbol"] == "SI=F"
    assert t["status"] == "delayed"
