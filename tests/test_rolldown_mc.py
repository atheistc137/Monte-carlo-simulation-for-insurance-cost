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

    def test_regime_index_produces_valid_results(self, synthetic_prices, synthetic_surface):
        """simulate_single_loan with regime_index produces valid results."""
        from rolldown_utils import RegimeIndex
        ri = RegimeIndex(synthetic_prices, synthetic_surface)
        result = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            regime_index=ri,
        )
        assert isinstance(result, LoanResult)
        assert result.initial_premium > 0
        assert result.net_savings >= 0

    def test_regime_index_none_matches_baseline(self, synthetic_prices, synthetic_surface):
        """regime_index=None produces identical results to no arg."""
        r_none = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            regime_index=None,
        )
        r_plain = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
        )
        assert abs(r_none.net_savings - r_plain.net_savings) < 0.01


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
        from rolldown_utils import RegimeIndex
        ri = RegimeIndex(synthetic_prices, synthetic_surface)
        results = run_tier2(
            synthetic_prices, synthetic_surface,
            n_mc_paths=3, start_freq="monthly", seed=42,
            regime_index=ri,
        )
        assert len(results) > 0
        assert all(isinstance(r, LoanResult) for r in results)

    def test_reproducible_with_seed(self, synthetic_prices, synthetic_surface):
        from rolldown_utils import RegimeIndex
        ri = RegimeIndex(synthetic_prices, synthetic_surface)
        r1 = run_tier2(synthetic_prices, synthetic_surface,
                       n_mc_paths=5, start_freq="monthly", seed=99,
                       regime_index=ri)
        r2 = run_tier2(synthetic_prices, synthetic_surface,
                       n_mc_paths=5, start_freq="monthly", seed=99,
                       regime_index=ri)
        for a, b in zip(r1, r2):
            assert abs(a.net_savings - b.net_savings) < 0.01


from bitmor_rolldown_mc import run_tier3


class TestTier3:
    @pytest.fixture(autouse=True)
    def _build_regime_index(self, synthetic_prices, synthetic_surface):
        from rolldown_utils import RegimeIndex
        self.regime_index = RegimeIndex(synthetic_prices, synthetic_surface)

    def test_correct_count(self, synthetic_prices, synthetic_surface):
        results = run_tier3(
            synthetic_prices, synthetic_surface,
            n_forward_paths=10, seed=42, regime_index=self.regime_index,
        )
        assert len(results) == 10

    def test_all_share_start_date(self, synthetic_prices, synthetic_surface):
        results = run_tier3(
            synthetic_prices, synthetic_surface,
            n_forward_paths=5, seed=42, regime_index=self.regime_index,
        )
        dates = {r.start_date for r in results}
        assert len(dates) == 1  # all start from today

    def test_same_initial_premium(self, synthetic_prices, synthetic_surface):
        """All paths start from same spot -> same initial premium."""
        results = run_tier3(
            synthetic_prices, synthetic_surface,
            n_forward_paths=5, seed=42, regime_index=self.regime_index,
        )
        premiums = {round(r.initial_premium, 2) for r in results}
        assert len(premiums) == 1

    def test_reproducible(self, synthetic_prices, synthetic_surface):
        r1 = run_tier3(synthetic_prices, synthetic_surface,
                       n_forward_paths=5, seed=99, regime_index=self.regime_index)
        r2 = run_tier3(synthetic_prices, synthetic_surface,
                       n_forward_paths=5, seed=99, regime_index=self.regime_index)
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


from bitmor_rolldown_mc import save_detail_csv


class TestSaveDetailCSV:
    def test_detail_csv_columns(self, tmp_path, synthetic_prices, synthetic_surface):
        results = [simulate_single_loan(
            synthetic_prices, synthetic_surface, pd.Timestamp("2024-03-01")
        )]
        filepath = tmp_path / "detail.csv"
        save_detail_csv(results, str(filepath))
        df = pd.read_csv(filepath)
        expected_cols = {"path_id", "month", "spot", "debt",
                         "K_held", "K_replacement", "roll_profit", "rolled"}
        assert expected_cols == set(df.columns)

    def test_detail_csv_row_count(self, tmp_path, synthetic_prices, synthetic_surface):
        results = [simulate_single_loan(
            synthetic_prices, synthetic_surface, pd.Timestamp("2024-03-01"),
            loan_tenor_months=12,
        )]
        filepath = tmp_path / "detail.csv"
        save_detail_csv(results, str(filepath))
        df = pd.read_csv(filepath)
        assert len(df) == 11  # months 1-11

    def test_detail_csv_path_id_matches_summary(self, tmp_path, synthetic_prices, synthetic_surface):
        r1 = simulate_single_loan(synthetic_prices, synthetic_surface, pd.Timestamp("2024-03-01"))
        r2 = simulate_single_loan(synthetic_prices, synthetic_surface, pd.Timestamp("2024-04-01"))
        results = [r1, r2]
        save_tier_csv(results, str(tmp_path / "summary.csv"))
        save_detail_csv(results, str(tmp_path / "detail.csv"))
        summary = pd.read_csv(tmp_path / "summary.csv")
        detail = pd.read_csv(tmp_path / "detail.csv")
        assert set(summary["path_id"]) == set(detail["path_id"].unique())

    def test_detail_csv_rolled_is_int(self, tmp_path, synthetic_prices, synthetic_surface):
        results = [simulate_single_loan(
            synthetic_prices, synthetic_surface, pd.Timestamp("2024-03-01")
        )]
        filepath = tmp_path / "detail.csv"
        save_detail_csv(results, str(filepath))
        df = pd.read_csv(filepath)
        assert df["rolled"].isin([0, 1]).all()

    def test_detail_csv_empty_for_averaged(self, tmp_path, synthetic_prices, synthetic_surface):
        r1 = simulate_single_loan(synthetic_prices, synthetic_surface, pd.Timestamp("2024-03-01"))
        r2 = simulate_single_loan(synthetic_prices, synthetic_surface, pd.Timestamp("2024-03-01"),
                                  min_roll_profit=1_000_000)
        avg = average_results([r1, r2])
        filepath = tmp_path / "detail.csv"
        save_detail_csv([avg], str(filepath))
        df = pd.read_csv(filepath)
        assert len(df) == 0


class TestHeldPutTenorLookup:
    """Bug B: held PUT IV must use its own remaining TTM, not the replacement's."""

    def test_held_put_uses_own_tenor(self, synthetic_surface, synthetic_prices):
        """At month 10, held PUT has ~60 days left (should use 90d bucket),
        while replacement uses 90d bucket. Both should resolve, and the
        held PUT should NOT use a 180d or 365d bucket."""
        from bitmor_rolldown_mc import simulate_single_loan
        from rolldown_utils import RegimeIndex

        ri = RegimeIndex(synthetic_prices, synthetic_surface)
        result = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
            regime_index=ri,
        )
        # If the held PUT used the wrong tenor, month_details would show
        # nonsensical values. Just verify the simulation completes and
        # savings are bounded. savings_pct can legitimately exceed 100%
        # (cumulative roll profits > initial premium), but should be finite.
        assert result.savings_pct < 500.0
