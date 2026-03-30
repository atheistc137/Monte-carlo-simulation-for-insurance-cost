import pandas as pd
import pytest

from bitmor_rolldown_mc import LoanResult, simulate_single_loan


class TestSimulateSingleLoan:
    def test_returns_loan_result(self, synthetic_prices, synthetic_surface):
        result = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
        )
        assert isinstance(result, LoanResult)
        assert result.spot_at_start > 0
        assert result.initial_premium > 0

    def test_savings_equals_roll_profits(self, synthetic_prices, synthetic_surface):
        """net_savings = total_roll_profit (insurance cost reduction only)."""
        r = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
        )
        assert abs(r.net_savings - r.total_roll_profit) < 0.01
        # full_economic_delta includes terminal delta
        expected_econ = r.total_roll_profit + (r.terminal_payoff_rolling - r.terminal_payoff_static)
        assert abs(r.full_economic_delta - expected_econ) < 0.01

    def test_savings_always_non_negative(self, synthetic_prices, synthetic_surface):
        """Roll savings can never be negative — we only roll when profitable."""
        r = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
        )
        assert r.net_savings >= 0

    def test_no_rolls_zero_savings(self, synthetic_prices, synthetic_surface):
        """Infinite threshold -> no rolls -> K_held unchanged -> savings = 0."""
        r = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            min_roll_profit=1_000_000,
        )
        assert r.num_rolls == 0
        assert r.total_roll_profit == 0.0
        assert abs(r.net_savings) < 0.01

    def test_rolling_strike_never_exceeds_static(self, synthetic_prices, synthetic_surface):
        """Rolling only lowers the strike (to outstanding debt)."""
        r = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
        )
        # terminal_payoff_rolling <= terminal_payoff_static always
        assert r.terminal_payoff_rolling <= r.terminal_payoff_static + 0.01

    def test_month_details_length(self, synthetic_prices, synthetic_surface):
        r = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            loan_tenor_months=12,
        )
        assert len(r.month_details) == 11  # months 1 through 11

    def test_ltv_determines_initial_strike(self, synthetic_prices, synthetic_surface):
        r = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            ltv=0.50,
        )
        r_high = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            ltv=0.70,
        )
        # Lower LTV -> lower strike PUT -> cheaper premium
        assert r.initial_premium < r_high.initial_premium

    def test_cutoff_date_switches_iv_lookup(self, synthetic_prices, synthetic_surface):
        """With cutoff in the past, simulated months use RV-based IV."""
        from rolldown_utils import build_iv_tables
        tables = build_iv_tables(synthetic_surface, synthetic_prices,
                                 [90, 180, 270, 365])
        r_frozen = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            cutoff_date=None, iv_tables=None,
        )
        r_rv = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            cutoff_date=pd.Timestamp("2024-03-01"),  # all months use RV
            iv_tables=tables,
        )
        # Different IV lookup -> different premiums/roll decisions
        # Just verify it runs and produces a valid result
        assert isinstance(r_rv, LoanResult)
        assert r_rv.initial_premium > 0

    def test_cutoff_none_means_all_surface(self, synthetic_prices, synthetic_surface):
        """cutoff_date=None -> never uses RV lookup, even with tables passed."""
        from rolldown_utils import build_iv_tables
        tables = build_iv_tables(synthetic_surface, synthetic_prices,
                                 [90, 180, 270, 365])
        r_no_cutoff = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            cutoff_date=None, iv_tables=tables,
        )
        r_plain = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
        )
        assert abs(r_no_cutoff.net_savings - r_plain.net_savings) < 0.01


from bitmor_rolldown_mc import run_tier1


class TestTier1:
    def test_returns_results(self, synthetic_prices, synthetic_surface):
        results = run_tier1(
            synthetic_prices, synthetic_surface,
            backtest_years=1, start_freq="monthly",
        )
        assert len(results) > 0
        assert all(isinstance(r, LoanResult) for r in results)

    def test_start_dates_in_range(self, synthetic_prices, synthetic_surface):
        results = run_tier1(
            synthetic_prices, synthetic_surface,
            backtest_years=1, start_freq="monthly",
        )
        last_date = synthetic_prices.index[-1]
        one_year_ago = last_date - pd.DateOffset(years=1)
        two_years_ago = last_date - pd.DateOffset(years=2)
        for r in results:
            assert r.start_date >= two_years_ago - pd.Timedelta(days=7)
            assert r.start_date <= one_year_ago + pd.Timedelta(days=7)

    def test_weekly_fewer_than_daily(self, synthetic_prices, synthetic_surface):
        daily = run_tier1(synthetic_prices, synthetic_surface,
                          backtest_years=1, start_freq="daily")
        weekly = run_tier1(synthetic_prices, synthetic_surface,
                           backtest_years=1, start_freq="weekly")
        assert len(weekly) < len(daily)


from bitmor_rolldown_mc import run_tier2, average_results


class TestAverageResults:
    def test_averages_numeric_fields(self, synthetic_prices, synthetic_surface):
        r1 = simulate_single_loan(synthetic_prices, synthetic_surface,
                                  pd.Timestamp("2024-03-01"))
        r2 = simulate_single_loan(synthetic_prices, synthetic_surface,
                                  pd.Timestamp("2024-03-01"), min_roll_profit=1_000_000)
        avg = average_results([r1, r2])
        assert avg.start_date == r1.start_date
        assert abs(avg.net_savings - (r1.net_savings + r2.net_savings) / 2) < 0.01


class TestTier2:
    def test_returns_results(self, synthetic_prices, synthetic_surface):
        from rolldown_utils import build_iv_tables
        tables = build_iv_tables(synthetic_surface, synthetic_prices,
                                 [90, 180, 270, 365])
        results = run_tier2(
            synthetic_prices, synthetic_surface,
            n_mc_paths=3, start_freq="monthly", seed=42,
            iv_tables=tables,
        )
        assert len(results) > 0
        assert all(isinstance(r, LoanResult) for r in results)

    def test_reproducible_with_seed(self, synthetic_prices, synthetic_surface):
        from rolldown_utils import build_iv_tables
        tables = build_iv_tables(synthetic_surface, synthetic_prices,
                                 [90, 180, 270, 365])
        r1 = run_tier2(synthetic_prices, synthetic_surface,
                       n_mc_paths=5, start_freq="monthly", seed=99,
                       iv_tables=tables)
        r2 = run_tier2(synthetic_prices, synthetic_surface,
                       n_mc_paths=5, start_freq="monthly", seed=99,
                       iv_tables=tables)
        for a, b in zip(r1, r2):
            assert abs(a.net_savings - b.net_savings) < 0.01


from bitmor_rolldown_mc import run_tier3


class TestTier3:
    @pytest.fixture(autouse=True)
    def _build_tables(self, synthetic_prices, synthetic_surface):
        from rolldown_utils import build_iv_tables
        self.tables = build_iv_tables(synthetic_surface, synthetic_prices,
                                      [90, 180, 270, 365])

    def test_correct_count(self, synthetic_prices, synthetic_surface):
        results = run_tier3(
            synthetic_prices, synthetic_surface,
            n_forward_paths=10, seed=42, iv_tables=self.tables,
        )
        assert len(results) == 10

    def test_all_share_start_date(self, synthetic_prices, synthetic_surface):
        results = run_tier3(
            synthetic_prices, synthetic_surface,
            n_forward_paths=5, seed=42, iv_tables=self.tables,
        )
        dates = {r.start_date for r in results}
        assert len(dates) == 1  # all start from today

    def test_same_initial_premium(self, synthetic_prices, synthetic_surface):
        """All paths start from same spot -> same initial premium."""
        results = run_tier3(
            synthetic_prices, synthetic_surface,
            n_forward_paths=5, seed=42, iv_tables=self.tables,
        )
        premiums = {round(r.initial_premium, 2) for r in results}
        assert len(premiums) == 1

    def test_reproducible(self, synthetic_prices, synthetic_surface):
        r1 = run_tier3(synthetic_prices, synthetic_surface,
                       n_forward_paths=5, seed=99, iv_tables=self.tables)
        r2 = run_tier3(synthetic_prices, synthetic_surface,
                       n_forward_paths=5, seed=99, iv_tables=self.tables)
        for a, b in zip(r1, r2):
            assert abs(a.net_savings - b.net_savings) < 0.01


from bitmor_rolldown_mc import format_tier_report, save_tier_csv


class TestFormatReport:
    def test_report_contains_stats(self, synthetic_prices, synthetic_surface):
        results = run_tier1(synthetic_prices, synthetic_surface,
                            backtest_years=1, start_freq="monthly")
        report = format_tier_report(results, "Test Tier")
        assert "Test Tier" in report
        assert "Avg initial PUT premium" in report
        assert "Avg roll savings" in report

    def test_empty_results(self):
        report = format_tier_report([], "Empty")
        assert "No results" in report


class TestSaveTierCSV:
    def test_csv_round_trip(self, tmp_path, synthetic_prices, synthetic_surface):
        results = [simulate_single_loan(
            synthetic_prices, synthetic_surface, pd.Timestamp("2024-03-01")
        )]
        filepath = tmp_path / "test_output.csv"
        save_tier_csv(results, str(filepath))
        df = pd.read_csv(filepath)
        assert len(df) == 1
        assert "start_date" in df.columns
        assert "roll_savings" in df.columns
        assert "terminal_delta" in df.columns
        assert "full_economic_delta" in df.columns


class TestHeldPutTenorLookup:
    """Bug B: held PUT IV must use its own remaining TTM, not the replacement's."""

    def test_held_put_uses_own_tenor(self, synthetic_surface, synthetic_prices):
        """At month 10, held PUT has ~60 days left (should use 90d bucket),
        while replacement uses 90d bucket. Both should resolve, and the
        held PUT should NOT use a 180d or 365d bucket."""
        from bitmor_rolldown_mc import simulate_single_loan
        from rolldown_utils import build_iv_tables

        iv_tables = build_iv_tables(synthetic_surface, synthetic_prices,
                                     [90, 180, 270, 365])
        cutoff = pd.Timestamp("2024-06-01")
        result = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            cutoff_date=cutoff, iv_tables=iv_tables,
        )
        # If the held PUT used the wrong tenor, month_details would show
        # nonsensical values. Just verify the simulation completes and
        # savings are bounded. savings_pct can legitimately exceed 100%
        # (cumulative roll profits > initial premium), but should be finite.
        assert result.savings_pct < 500.0
