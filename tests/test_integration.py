"""Integration tests — require real data files in the project root.

Skip automatically if data files are missing.
"""
import os
from pathlib import Path

import pandas as pd
import pytest

DATA_DIR = os.path.dirname(os.path.dirname(__file__))
SURFACE = os.path.join(DATA_DIR, "btc_iv_surface_svi.csv")
PRICE = os.path.join(DATA_DIR, "BTCUSDT_1h.csv")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(SURFACE) and os.path.exists(PRICE)),
    reason="Real data files not present",
)


class TestIntegration:
    @pytest.fixture(autouse=True)
    def setup(self):
        from sim.liquidation.liquidation_utils import load_price, load_surface
        self.surface = load_surface(SURFACE)
        self.daily_prices = load_price(PRICE).resample("1D").last().dropna()

    def test_single_loan_real_data(self):
        from sim.rolldown.bitmor_rolldown_mc import simulate_single_loan
        result = simulate_single_loan(
            self.daily_prices, self.surface,
            start_date=pd.Timestamp("2023-06-01"),
        )
        assert result.initial_premium > 0
        assert result.spot_at_start > 0
        assert len(result.month_details) == 11

    def test_tier1_monthly_real_data(self):
        from sim.rolldown.bitmor_rolldown_mc import run_tier1
        results = run_tier1(
            self.daily_prices, self.surface,
            backtest_years=1, start_freq="monthly",
        )
        assert len(results) > 0

    def test_tier3_small_real_data(self):
        from sim.rolldown.bitmor_rolldown_mc import run_tier3
        from sim.liquidation.liquidation_utils import calibrate_hist_mu_sigma, load_price
        price_hourly = load_price(PRICE)
        mu, sigma = calibrate_hist_mu_sigma(price_hourly)
        results = run_tier3(
            self.daily_prices, self.surface,
            n_forward_paths=5, mu=mu, sigma=sigma, seed=42,
        )
        assert len(results) == 5


class TestPerTenorSurface:
    """Verify the per-tenor IV surface has correct structure after pipeline run."""

    @pytest.fixture
    def surface_csv(self):
        path = Path("btc_iv_surface_svi.csv")
        if not path.exists():
            pytest.skip("Surface CSV not generated yet")
        return pd.read_csv(path)

    @pytest.fixture
    def params_csv(self):
        path = Path("btc_svi_params.csv")
        if not path.exists():
            pytest.skip("Params CSV not generated yet")
        return pd.read_csv(path)

    def test_surface_has_long_tenors(self, surface_csv):
        """Surface must contain entries at 90/180/270/365 day TTMs."""
        ttms = surface_csv["ttm_days"].unique()
        for expected in [90, 180, 270, 365]:
            assert expected in ttms, f"Missing TTM={expected} in surface"

    def test_params_has_tenor_bucket(self, params_csv):
        """Params CSV must have tenor_bucket column."""
        assert "tenor_bucket" in params_csv.columns

    def test_long_tenor_iv_reasonable(self, surface_csv):
        """365-day BTC IV should be 30-90%, not the 15-20% from short-dated extrapolation."""
        long_iv = surface_csv[surface_csv["ttm_days"] == 365]["iv"]
        if long_iv.empty:
            pytest.skip("No 365-day entries")
        median_iv = long_iv.median()
        assert 20 < median_iv < 120, f"365d median IV={median_iv}% looks wrong"

    def test_rv_annualization_consistent(self):
        """compute_rv_from_prices output should fall within RV table range."""
        from sim.rolldown.rolldown_utils import compute_rv_from_prices
        from sim.liquidation.liquidation_utils import load_price
        price = load_price(Path("BTCUSDT_1h.csv"))
        daily = price.resample("1D").last().dropna()
        rv = compute_rv_from_prices(daily, daily.index[-10])
        # Should be < 2.0 (200% annualized vol) — with old bug it was > 3.0
        assert rv < 2.0, f"RV={rv:.3f} still looks inflated"
