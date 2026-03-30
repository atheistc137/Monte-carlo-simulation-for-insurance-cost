import numpy as np
import pandas as pd
import pytest

from rolldown_utils import map_tenor_bucket


class TestMapTenorBucket:
    def test_12m_bucket(self):
        assert map_tenor_bucket(12) == 365
        assert map_tenor_bucket(11) == 365
        assert map_tenor_bucket(10) == 365

    def test_9m_bucket(self):
        assert map_tenor_bucket(9) == 270
        assert map_tenor_bucket(8) == 270
        assert map_tenor_bucket(7) == 270

    def test_6m_bucket(self):
        assert map_tenor_bucket(6) == 180
        assert map_tenor_bucket(5) == 180
        assert map_tenor_bucket(4) == 180

    def test_3m_bucket(self):
        assert map_tenor_bucket(3) == 90
        assert map_tenor_bucket(2) == 90
        assert map_tenor_bucket(1) == 90

    def test_fallback_to_longest(self):
        """Remaining months exceeding all available tenors uses the longest."""
        assert map_tenor_bucket(15) == 365


from rolldown_utils import lookup_iv


class TestLookupIV:
    def test_exact_date(self, synthetic_surface):
        iv = lookup_iv(synthetic_surface, pd.Timestamp("2024-03-01"), 90, 0.7)
        assert 0 < iv < 2.0  # decimal, not percentage

    def test_nearest_date_fallback(self, synthetic_surface):
        """Dates between surface dates fall back to most recent available."""
        iv_mid = lookup_iv(synthetic_surface, pd.Timestamp("2024-03-15"), 90, 0.7)
        iv_exact = lookup_iv(synthetic_surface, pd.Timestamp("2024-03-01"), 90, 0.7)
        assert iv_mid == iv_exact

    def test_converts_pct_to_decimal(self, synthetic_surface):
        iv = lookup_iv(synthetic_surface, pd.Timestamp("2024-06-01"), 365, 1.0)
        # Synthetic surface stores ~47% -> should return ~0.47
        assert iv < 1.0

    def test_no_data_raises(self, synthetic_surface):
        with pytest.raises(ValueError, match="No surface data"):
            lookup_iv(synthetic_surface, pd.Timestamp("2020-01-01"), 90, 0.7)

    def test_uses_correct_tenor_when_available(self, synthetic_surface):
        """When multiple tenors exist, lookup must use the nearest TTM,
        not a distant one that would give wrong vol for the pricing horizon."""
        # synthetic_surface has TTMs [90, 180, 270, 365]
        iv_90 = lookup_iv(synthetic_surface, pd.Timestamp("2024-06-01"), 90, 0.7)
        iv_365 = lookup_iv(synthetic_surface, pd.Timestamp("2024-06-01"), 365, 0.7)
        # These should differ because the synthetic surface has term structure
        assert iv_90 != iv_365

    def test_nearest_moneyness(self, synthetic_surface):
        """Moneyness not on grid snaps to nearest available point."""
        iv = lookup_iv(synthetic_surface, pd.Timestamp("2024-06-01"), 90, 0.75)
        iv_grid = lookup_iv(synthetic_surface, pd.Timestamp("2024-06-01"), 90, 0.7)
        # 0.75 is equidistant from 0.7 and 0.8; argmin picks 0.7 (first)
        assert iv == iv_grid


from rolldown_utils import nearest_price, generate_gbm_path, compute_rv_from_prices, build_iv_tables


class TestNearestPrice:
    def test_exact_date(self, synthetic_prices):
        p = nearest_price(synthetic_prices, pd.Timestamp("2024-06-15"))
        assert p > 0
        assert isinstance(p, float)

    def test_between_dates(self, synthetic_prices):
        """Should find nearest available date."""
        p = nearest_price(synthetic_prices, pd.Timestamp("2024-06-15 12:00:00"))
        assert p > 0


class TestGenerateGBMPath:
    def test_shape(self):
        path = generate_gbm_path(100_000, 0.05, 0.5, 365, np.random.default_rng(42))
        assert len(path) == 366  # n_days + 1

    def test_starts_at_spot(self):
        path = generate_gbm_path(100_000, 0.05, 0.5, 365, np.random.default_rng(42))
        assert path[0] == 100_000.0

    def test_all_positive(self):
        path = generate_gbm_path(100_000, 0.05, 0.5, 365, np.random.default_rng(42))
        assert all(p > 0 for p in path)

    def test_reproducible(self):
        p1 = generate_gbm_path(100_000, 0.05, 0.5, 365, np.random.default_rng(42))
        p2 = generate_gbm_path(100_000, 0.05, 0.5, 365, np.random.default_rng(42))
        np.testing.assert_array_equal(p1, p2)


class TestComputeRV:
    def test_positive_rv(self, synthetic_prices):
        rv = compute_rv_from_prices(synthetic_prices, pd.Timestamp("2024-06-15"))
        assert rv > 0

    def test_reasonable_range(self, synthetic_prices):
        rv = compute_rv_from_prices(synthetic_prices, pd.Timestamp("2024-06-15"))
        assert rv < 5.0  # annualised vol under 500%

    def test_rv_matches_table_annualization(self, synthetic_prices):
        """RV from compute_rv_from_prices must use same annualization as
        build_weekly_iv_table (sqrt(365/window_days)), not sqrt(365)."""
        import math
        rv = compute_rv_from_prices(synthetic_prices, pd.Timestamp("2024-06-15"))
        # With sqrt(365/7) annualization, RV for synthetic_prices (daily sigma=0.02)
        # should be roughly 0.02 * sqrt(365/7) ~= 0.144
        # With the old sqrt(365) bug it would be ~0.02 * sqrt(365) ~= 0.382
        # Threshold at 0.25 cleanly separates the two regimes
        assert rv < 0.25, (
            f"RV={rv:.3f} too high — likely using sqrt(365) instead of sqrt(365/window_days)"
        )

    def test_short_window_returns_zero(self):
        """Fewer than 3 data points -> 0."""
        tiny = pd.Series([100_000.0, 100_100.0],
                         index=pd.date_range("2024-01-01", periods=2, freq="D"))
        assert compute_rv_from_prices(tiny, pd.Timestamp("2024-01-02")) == 0.0


class TestBuildIVTables:
    def test_builds_tables_for_available_tenors(self, synthetic_surface, synthetic_prices):
        tables = build_iv_tables(synthetic_surface, synthetic_prices, [90, 180, 270, 365])
        assert len(tables) > 0
        for td, tbl in tables.items():
            assert not tbl.empty
            assert "iv" in tbl.columns

    def test_maps_to_nearest_tenor(self, synthetic_surface, synthetic_prices):
        """If surface lacks 120-day tenor, uses nearest available."""
        tables = build_iv_tables(synthetic_surface, synthetic_prices, [120])
        assert 120 in tables  # keyed by requested tenor, built from nearest


from rolldown_utils import evaluate_roll


class TestEvaluateRoll:
    def test_profitable_roll(self):
        """K_held > debt with same vol -> held PUT worth more -> profit."""
        profit, should = evaluate_roll(
            spot=100_000, K_held=80_000, held_time_remaining=0.75,
            debt_outstanding=70_000, replacement_tenor=0.75,
            r=0.0, iv_held=0.5, iv_replacement=0.5, min_roll_profit=200,
        )
        assert profit > 200
        assert should is True

    def test_below_threshold(self):
        """Tiny strike difference -> profit below $200 threshold."""
        profit, should = evaluate_roll(
            spot=100_000, K_held=70_100, held_time_remaining=0.75,
            debt_outstanding=70_000, replacement_tenor=0.75,
            r=0.0, iv_held=0.5, iv_replacement=0.5, min_roll_profit=200,
        )
        assert should is False

    def test_unprofitable_roll(self):
        """K_held < debt -> replacement costs more -> negative profit."""
        profit, should = evaluate_roll(
            spot=100_000, K_held=60_000, held_time_remaining=0.25,
            debt_outstanding=70_000, replacement_tenor=0.75,
            r=0.0, iv_held=0.5, iv_replacement=0.5, min_roll_profit=200,
        )
        assert profit < 0
        assert should is False


import datetime as _dt
from btc_iv import quarterly_expiries


class TestQuarterlyExpiries:
    def test_returns_four_dates(self):
        expiries = quarterly_expiries(_dt.date(2025, 1, 15))
        assert len(expiries) == 4
        assert all(isinstance(d, _dt.date) for d in expiries)

    def test_all_future(self):
        ref = _dt.date(2025, 1, 15)
        for exp in quarterly_expiries(ref):
            assert exp > ref

    def test_quarterly_months(self):
        expiries = quarterly_expiries(_dt.date(2025, 1, 15))
        months = {d.month for d in expiries}
        assert months.issubset({3, 6, 9, 12})

    def test_all_fridays(self):
        for exp in quarterly_expiries(_dt.date(2025, 1, 15)):
            assert exp.weekday() == 4  # Friday


from rolldown_utils import map_tenor_bucket_days


class TestMapTenorBucketDays:
    def test_exact_match(self):
        assert map_tenor_bucket_days(90, [90, 180, 270, 365]) == 90

    def test_rounds_up_to_nearest(self):
        assert map_tenor_bucket_days(100, [90, 180, 270, 365]) == 180

    def test_below_smallest_returns_smallest(self):
        assert map_tenor_bucket_days(30, [90, 180, 270, 365]) == 90

    def test_above_largest_returns_largest(self):
        assert map_tenor_bucket_days(400, [90, 180, 270, 365]) == 365

    def test_single_tenor(self):
        assert map_tenor_bucket_days(200, [365]) == 365
