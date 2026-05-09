"""Tests for btc_iv.py bulk data fetch."""
import datetime as dt
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from sim.ivsurface.btc_iv import (
    parse_expiry_from_instrument,
    collect_surface_bulk,
    quarterly_expiries,
    month_end_expiry,
)


class TestParseExpiryFromInstrument:
    def test_standard_format(self):
        assert parse_expiry_from_instrument("BTC-27JUN25-100000-C") == "2025-06-27"

    def test_put_option(self):
        assert parse_expiry_from_instrument("BTC-27JUN25-50000-P") == "2025-06-27"

    def test_december(self):
        assert parse_expiry_from_instrument("BTC-26DEC25-80000-C") == "2025-12-26"

    def test_invalid_returns_none(self):
        assert parse_expiry_from_instrument("INVALID") is None


class TestCollectSurfaceBulk:
    @patch("sim.ivsurface.btc_iv.call_api")
    def test_filters_to_target_expiry(self, mock_api):
        """Only trades matching target expiry dates are kept."""
        mock_api.return_value = {
            "trades": [
                {
                    "instrument_name": "BTC-27JUN25-100000-C",
                    "timestamp": 1000,
                    "iv": 0.50,
                    "price": 0.05,
                    "amount": 1.0,
                },
                {
                    "instrument_name": "BTC-28MAR25-90000-P",
                    "timestamp": 1001,
                    "iv": 0.45,
                    "price": 0.03,
                    "amount": 1.0,
                },
            ],
            "has_more": False,
        }
        day = dt.date(2025, 3, 15)
        targets = [dt.date(2025, 6, 27)]  # only Jun expiry
        df = collect_surface_bulk(day, targets)
        assert len(df) == 1
        assert df.iloc[0]["instrument"] == "BTC-27JUN25-100000-C"

    @patch("sim.ivsurface.btc_iv.call_api")
    def test_empty_day_returns_empty(self, mock_api):
        mock_api.return_value = {"trades": [], "has_more": False}
        df = collect_surface_bulk(dt.date(2025, 1, 1), [dt.date(2025, 1, 31)])
        assert df.empty

    @patch("sim.ivsurface.btc_iv.call_api")
    def test_deduplicates_to_last_trade(self, mock_api):
        """Multiple trades for same instrument -> keep last by timestamp."""
        mock_api.return_value = {
            "trades": [
                {"instrument_name": "BTC-27JUN25-100000-C", "timestamp": 100,
                 "iv": 0.40, "price": 0.04, "amount": 1.0},
                {"instrument_name": "BTC-27JUN25-100000-C", "timestamp": 200,
                 "iv": 0.50, "price": 0.05, "amount": 1.0},
            ],
            "has_more": False,
        }
        day = dt.date(2025, 3, 15)
        df = collect_surface_bulk(day, [dt.date(2025, 6, 27)])
        assert len(df) == 1
        assert df.iloc[0]["iv"] == 0.50  # later trade wins
