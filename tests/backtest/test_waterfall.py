"""Tests for the liquidation waterfall."""
import pytest
from liquidation_waterfall import compute_waterfall, WaterfallResult


class TestWaterfall:
    def test_btc_covers_everything(self):
        """When BTC value alone covers debt + fee, surplus goes to protocol."""
        r = compute_waterfall(
            allocated_btc=1.0,
            spot=100_000,
            put_mtm=5_000,
            debt=60_000,
            liq_buffer=0.03,
        )
        assert r.coverage_ratio > 1.0
        assert r.shortfall_usd == 0.0
        assert r.surplus_to_protocol > 0.0
        # Total proceeds = 100k + 5k = 105k
        # Liabilities = 60k * 1.03 = 61.8k
        assert r.total_proceeds == pytest.approx(105_000)
        assert r.total_liabilities == pytest.approx(61_800)

    def test_exact_coverage(self):
        """When proceeds exactly equal liabilities."""
        # debt=100k, buffer=3%, liabilities=103k
        # btc=0.5 @ 100k = 50k, put=53k → total=103k
        r = compute_waterfall(
            allocated_btc=0.5,
            spot=100_000,
            put_mtm=53_000,
            debt=100_000,
            liq_buffer=0.03,
        )
        assert r.coverage_ratio == pytest.approx(1.0, rel=1e-6)
        assert r.shortfall_usd == pytest.approx(0.0, abs=1)
        assert r.surplus_to_protocol == pytest.approx(0.0, abs=1)

    def test_shortfall(self):
        """When BTC + PUT cannot cover debt + fee."""
        r = compute_waterfall(
            allocated_btc=1.0,
            spot=30_000,       # BTC dropped hard
            put_mtm=10_000,    # PUT helps but not enough
            debt=60_000,
            liq_buffer=0.03,
        )
        # Proceeds = 30k + 10k = 40k
        # Liabilities = 60k * 1.03 = 61.8k
        assert r.coverage_ratio < 1.0
        assert r.shortfall_usd == pytest.approx(21_800, rel=0.01)
        assert r.surplus_to_protocol == 0.0

    def test_zero_put(self):
        """PUT is worthless (deep OTM at default)."""
        r = compute_waterfall(
            allocated_btc=1.0,
            spot=120_000,
            put_mtm=0.0,
            debt=70_000,
            liq_buffer=0.03,
        )
        assert r.coverage_ratio > 1.0
        assert r.total_proceeds == pytest.approx(120_000)
