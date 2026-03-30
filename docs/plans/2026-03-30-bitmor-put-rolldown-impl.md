# Bitmor PUT Roll-Down Simulator — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a three-tier simulator that quantifies average cost savings from rolling PUT hedges on amortizing BTC loans, as specified in [the design doc](2026-03-30-bitmor-put-rolldown-design.md).

**Architecture:** Core `simulate_single_loan()` function is tier-agnostic — it takes a daily price series and IV surface, so tier orchestrators supply real or simulated prices interchangeably. Tier 1 uses 100% historical data, Tier 2 splices real prices with GBM tails, Tier 3 generates full GBM paths. Utilities in `rolldown_utils.py`, entry point in `bitmor_rolldown_mc.py`.

**IV–price dependency:** During simulated months (Tier 2 tail, all of Tier 3), IV is not frozen — it is looked up via the existing `lookup_iv_weekly(table, realized_vol, moneyness)` mechanism from `liquidation_utils.py`. This captures the empirical correlation between price action and IV: crash paths produce high realized vol → high IV lookups, calm paths → low IV. A `cutoff_date` parameter tells `simulate_single_loan` when to switch from direct surface lookup (real data) to RV-based lookup (simulated data). Per-tenor weekly IV tables (`{90: tbl, 180: tbl, ...}`) are built once by the tier orchestrator and passed in.

**Tech Stack:** Python 3.10+, numpy, pandas, scipy (existing); pytest (testing)

**Key reuse from existing code:**
- `bs_price(S, K, T, r, sigma, call)` from `liquidation_utils.py` — Black-Scholes pricing
- `load_surface(path)` / `load_price(path)` — CSV loaders
- `calibrate_hist_mu_sigma(px)` — GBM drift/vol from price history
- `build_amortisation_schedule(principal, rate, years, ppy)` — amort schedule
- `build_weekly_iv_table(surface, price, tenor_days)` — empirical (RV, moneyness) → IV table
- `lookup_iv_weekly(tbl, rv, mny)` — nearest-neighbour IV lookup from RV table

**Data note:** The current IV surface (`btc_iv_surface_svi.csv`) covers TTM 15–60 days. The simulation needs 90/180/270/365-day tenors. Task 11 extends the IV pipeline; until then, `build_iv_tables` maps each requested tenor to the nearest available TTM in the surface (e.g., 90 → 60) so the RV-based lookup still captures the vol-IV correlation, just with approximate absolute levels. All tests use synthetic fixtures with correct tenors, so simulation code is fully testable before the pipeline extension.

---

### Task 1: Test Infrastructure & Shared Fixtures

**Files:**
- Create: `tests/conftest.py`

**Step 1: Create conftest with synthetic surface and price fixtures**

```python
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_surface():
    """IV surface with quarterly tenors, indexed like load_surface() output.

    Columns after set_index: iv (percentage, e.g. 50.0 = 50%).
    Index levels: (date, ttm_days, mny).
    """
    dates = pd.date_range("2024-01-01", "2025-03-01", freq="MS")
    ttm_values = [90, 180, 270, 365]
    mny_values = np.arange(0.4, 1.6, 0.1).round(1)

    rows = []
    for d in dates:
        for ttm in ttm_values:
            for mny in mny_values:
                # Simple smile: higher IV for OTM puts, slight term-structure decline
                iv = 50.0 + 20.0 * max(0.0, 1.0 - mny) - 3.0 * (ttm / 365)
                rows.append({"date": d, "ttm_days": int(ttm), "mny": mny, "iv": iv})

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["ttm_days"] = df["ttm_days"].astype(int)
    return df.set_index(["date", "ttm_days", "mny"]).sort_index()


@pytest.fixture
def synthetic_prices():
    """Daily BTC prices: starts at $100k, mild random walk.

    Returns pd.Series indexed by date, like load_price().resample('1D').last().
    """
    dates = pd.date_range("2024-01-01", "2025-06-30", freq="D")
    rng = np.random.default_rng(42)
    log_returns = rng.normal(0.0002, 0.02, len(dates) - 1)
    prices = np.empty(len(dates))
    prices[0] = 100_000.0
    for i in range(1, len(dates)):
        prices[i] = prices[i - 1] * np.exp(log_returns[i - 1])
    return pd.Series(prices, index=dates, name="close")
```

**Step 2: Verify fixtures load**

Run: `cd "/mnt/c/Users/suryansh/2025 projects/Monte carlo for insurance cost" && python -m pytest tests/conftest.py --collect-only`
Expected: collected 0 items (no tests yet, but no import errors)

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared fixtures for rolldown simulator tests"
```

---

### Task 2: Tenor Bucket Mapping

**Files:**
- Create: `rolldown_utils.py`
- Create: `tests/test_rolldown_utils.py`

**Step 1: Write failing tests**

```python
# tests/test_rolldown_utils.py
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
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_utils.py::TestMapTenorBucket -v`
Expected: FAIL — `ImportError: cannot import name 'map_tenor_bucket' from 'rolldown_utils'`

**Step 3: Write implementation**

```python
# rolldown_utils.py
"""
Utility helpers for the Bitmor PUT roll-down simulator.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from liquidation_utils import bs_price

# Mapping from option tenor (months) to calendar days
TENOR_DAYS: dict[int, int] = {3: 90, 6: 180, 9: 270, 12: 365}


def map_tenor_bucket(remaining_months: int,
                     available_tenors: list[int] | None = None) -> int:
    """Map remaining loan months to the smallest available tenor bucket (in days).

    Rule: pick the smallest available tenor >= remaining_months.
    Fallback: longest available tenor.
    """
    if available_tenors is None:
        available_tenors = [3, 6, 9, 12]
    for t in sorted(available_tenors):
        if t >= remaining_months:
            return TENOR_DAYS[t]
    return TENOR_DAYS[max(available_tenors)]
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_utils.py::TestMapTenorBucket -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add rolldown_utils.py tests/test_rolldown_utils.py
git commit -m "feat: add tenor bucket mapping for rolldown strategy"
```

---

### Task 3: IV Surface Lookup

**Files:**
- Modify: `rolldown_utils.py`
- Modify: `tests/test_rolldown_utils.py`

**Step 1: Write failing tests**

Append to `tests/test_rolldown_utils.py`:

```python
import pytest
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
        # Synthetic surface stores ~47% → should return ~0.47
        assert iv < 1.0

    def test_no_data_raises(self, synthetic_surface):
        with pytest.raises(ValueError, match="No surface data"):
            lookup_iv(synthetic_surface, pd.Timestamp("2020-01-01"), 90, 0.7)

    def test_nearest_moneyness(self, synthetic_surface):
        """Moneyness not on grid snaps to nearest available point."""
        iv = lookup_iv(synthetic_surface, pd.Timestamp("2024-06-01"), 90, 0.75)
        iv_grid = lookup_iv(synthetic_surface, pd.Timestamp("2024-06-01"), 90, 0.8)
        # 0.75 is between 0.7 and 0.8; nearest is 0.8
        assert iv == iv_grid
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_utils.py::TestLookupIV -v`
Expected: FAIL — `ImportError: cannot import name 'lookup_iv'`

**Step 3: Write implementation**

Append to `rolldown_utils.py`:

```python
def lookup_iv(surface: pd.DataFrame, date: pd.Timestamp,
              ttm_days: int, moneyness: float) -> float:
    """Look up IV from SVI surface by nearest (date ≤ query, ttm, moneyness).

    Returns IV as a decimal (e.g. 0.50 for 50%).
    The surface stores IV in percentage form.
    """
    dates = surface.index.get_level_values("date").unique()
    available = dates[dates <= date]
    if len(available) == 0:
        raise ValueError(f"No surface data on or before {date}")
    nearest_date = available[-1]

    day_slice = surface.loc[nearest_date]

    ttm_values = day_slice.index.get_level_values("ttm_days").unique()
    nearest_ttm = int(ttm_values[np.abs(ttm_values - ttm_days).argmin()])

    ttm_slice = day_slice.loc[nearest_ttm]

    mny_values = ttm_slice.index.get_level_values("mny").values.astype(float)
    nearest_mny = mny_values[np.abs(mny_values - moneyness).argmin()]

    iv_pct = float(ttm_slice.loc[nearest_mny, "iv"])
    return iv_pct / 100.0
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_utils.py::TestLookupIV -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add rolldown_utils.py tests/test_rolldown_utils.py
git commit -m "feat: add IV surface lookup with nearest-neighbor fallback"
```

---

### Task 4: Price Lookup & GBM Path Generation

**Files:**
- Modify: `rolldown_utils.py`
- Modify: `tests/test_rolldown_utils.py`

**Step 1: Write failing tests**

Append to `tests/test_rolldown_utils.py`:

```python
import numpy as np
from rolldown_utils import nearest_price, generate_gbm_path


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

    def test_short_window_returns_zero(self):
        """Fewer than 3 data points → 0."""
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
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_utils.py::TestNearestPrice tests/test_rolldown_utils.py::TestGenerateGBMPath tests/test_rolldown_utils.py::TestComputeRV tests/test_rolldown_utils.py::TestBuildIVTables -v`
Expected: FAIL — `ImportError`

**Step 3: Write implementation**

Append to `rolldown_utils.py`:

```python
import logging

from liquidation_utils import bs_price, build_weekly_iv_table


def nearest_price(daily_prices: pd.Series,
                  target_date: pd.Timestamp) -> float:
    """Get the price nearest to target_date from a daily price series."""
    idx = daily_prices.index.get_indexer([target_date], method="nearest")[0]
    if idx < 0:
        raise ValueError(f"No price data near {target_date}")
    return float(daily_prices.iloc[idx])


def generate_gbm_path(spot0: float, mu: float, sigma: float,
                      n_days: int, rng: np.random.Generator) -> np.ndarray:
    """Generate a daily GBM price path (vectorised).

    Returns array of length n_days + 1 (includes spot0 at index 0).
    """
    dt = 1.0 / 365
    z = rng.standard_normal(n_days)
    log_returns = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
    prices = np.empty(n_days + 1)
    prices[0] = spot0
    prices[1:] = spot0 * np.exp(np.cumsum(log_returns))
    return prices


def compute_rv_from_prices(daily_prices: pd.Series,
                           as_of_date: pd.Timestamp,
                           window_days: int = 7) -> float:
    """Annualised realized volatility from a trailing daily price window.

    Used during simulated months to drive the RV-based IV lookup.
    """
    window_start = as_of_date - pd.Timedelta(days=window_days + 2)
    window = daily_prices[window_start:as_of_date]
    if len(window) < 3:
        return 0.0
    log_ret = np.log(window / window.shift(1)).dropna()
    return float(log_ret.std() * np.sqrt(365))


def build_iv_tables(surface: pd.DataFrame, price: pd.Series,
                    tenor_days_list: list[int]) -> dict[int, pd.DataFrame]:
    """Build weekly (RV, moneyness) -> IV lookup tables for each tenor bucket.

    Maps each requested tenor to the nearest available TTM in the surface,
    so the RV-IV correlation is captured even before the IV pipeline is
    extended to include quarterly tenors.
    """
    available_ttm = sorted(surface.index.get_level_values("ttm_days").unique())
    tables: dict[int, pd.DataFrame] = {}
    for td in tenor_days_list:
        nearest_ttm = int(min(available_ttm, key=lambda x: abs(x - td)))
        try:
            tables[td] = build_weekly_iv_table(surface, price, tenor_days=nearest_ttm)
        except (ValueError, RuntimeError) as e:
            logging.warning("Cannot build IV table for %d-day tenor "
                            "(nearest %d): %s", td, nearest_ttm, e)
    return tables
```

**Note on imports:** The `from liquidation_utils import bs_price` line added in Task 2 should be updated to also import `build_weekly_iv_table`:

```python
from liquidation_utils import bs_price, build_weekly_iv_table
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_utils.py::TestNearestPrice tests/test_rolldown_utils.py::TestGenerateGBMPath tests/test_rolldown_utils.py::TestComputeRV tests/test_rolldown_utils.py::TestBuildIVTables -v`
Expected: 11 passed

**Step 5: Commit**

```bash
git add rolldown_utils.py tests/test_rolldown_utils.py
git commit -m "feat: add nearest_price, GBM path, RV computation, and IV table builder"
```

---

### Task 5: Roll Evaluation

**Files:**
- Modify: `rolldown_utils.py`
- Modify: `tests/test_rolldown_utils.py`

**Step 1: Write failing tests**

Append to `tests/test_rolldown_utils.py`:

```python
from rolldown_utils import evaluate_roll


class TestEvaluateRoll:
    def test_profitable_roll(self):
        """K_held > debt with same vol → held PUT worth more → profit."""
        profit, should = evaluate_roll(
            spot=100_000, K_held=80_000, held_time_remaining=0.75,
            debt_outstanding=70_000, replacement_tenor=0.75,
            r=0.0, iv_held=0.5, iv_replacement=0.5, min_roll_profit=200,
        )
        assert profit > 200
        assert should is True

    def test_below_threshold(self):
        """Tiny strike difference → profit below $200 threshold."""
        profit, should = evaluate_roll(
            spot=100_000, K_held=70_100, held_time_remaining=0.75,
            debt_outstanding=70_000, replacement_tenor=0.75,
            r=0.0, iv_held=0.5, iv_replacement=0.5, min_roll_profit=200,
        )
        assert should is False

    def test_unprofitable_roll(self):
        """K_held < debt → replacement costs more → negative profit."""
        profit, should = evaluate_roll(
            spot=100_000, K_held=60_000, held_time_remaining=0.25,
            debt_outstanding=70_000, replacement_tenor=0.75,
            r=0.0, iv_held=0.5, iv_replacement=0.5, min_roll_profit=200,
        )
        assert profit < 0
        assert should is False
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_utils.py::TestEvaluateRoll -v`
Expected: FAIL — `ImportError`

**Step 3: Write implementation**

Append to `rolldown_utils.py`:

```python
def evaluate_roll(spot: float, K_held: float,
                  held_time_remaining: float,
                  debt_outstanding: float,
                  replacement_tenor: float,
                  r: float,
                  iv_held: float, iv_replacement: float,
                  min_roll_profit: float = 200.0) -> tuple[float, bool]:
    """Evaluate whether a PUT roll is profitable.

    Returns (roll_profit, should_roll).
    """
    held_value = bs_price(spot, K_held, held_time_remaining, r, iv_held, call=False)
    replacement_cost = bs_price(spot, debt_outstanding, replacement_tenor, r,
                                iv_replacement, call=False)
    profit = held_value - replacement_cost
    return profit, profit >= min_roll_profit
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_utils.py::TestEvaluateRoll -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add rolldown_utils.py tests/test_rolldown_utils.py
git commit -m "feat: add PUT roll evaluation logic"
```

---

### Task 6: LoanResult & simulate_single_loan

**Files:**
- Create: `bitmor_rolldown_mc.py`
- Create: `tests/test_rolldown_mc.py`

**Step 1: Write failing tests**

```python
# tests/test_rolldown_mc.py
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

    def test_savings_identity(self, synthetic_prices, synthetic_surface):
        """net_savings = total_roll_profit + (terminal_rolling - terminal_static)."""
        r = simulate_single_loan(
            synthetic_prices, synthetic_surface,
            start_date=pd.Timestamp("2024-03-01"),
        )
        expected = r.total_roll_profit + (r.terminal_payoff_rolling - r.terminal_payoff_static)
        assert abs(r.net_savings - expected) < 0.01

    def test_no_rolls_zero_savings(self, synthetic_prices, synthetic_surface):
        """Infinite threshold → no rolls → K_held unchanged → savings = 0."""
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
        # Lower LTV → lower strike PUT → cheaper premium
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
        # Different IV lookup → different premiums/roll decisions
        # Just verify it runs and produces a valid result
        assert isinstance(r_rv, LoanResult)
        assert r_rv.initial_premium > 0

    def test_cutoff_none_means_all_surface(self, synthetic_prices, synthetic_surface):
        """cutoff_date=None → never uses RV lookup, even with tables passed."""
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
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_mc.py::TestSimulateSingleLoan -v`
Expected: FAIL — `ImportError: cannot import name 'LoanResult' from 'bitmor_rolldown_mc'`

**Step 3: Write implementation**

```python
# bitmor_rolldown_mc.py
#!/usr/bin/env python3
"""
Bitmor PUT Roll-Down Cost Reduction Simulator.

Three-tier analysis:
  Tier 1: Pure historical backtest
  Tier 2: Recent loans with simulated GBM tails
  Tier 3: Forward MC from today's price
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from liquidation_utils import (
    bs_price,
    build_amortisation_schedule,
    calibrate_hist_mu_sigma,
    load_price,
    load_surface,
    lookup_iv_weekly,
)
from rolldown_utils import (
    build_iv_tables,
    compute_rv_from_prices,
    evaluate_roll,
    generate_gbm_path,
    lookup_iv,
    map_tenor_bucket,
    nearest_price,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class LoanResult:
    start_date: pd.Timestamp
    spot_at_start: float
    initial_premium: float
    roll_profits: list[float]
    total_roll_profit: float
    terminal_payoff_static: float
    terminal_payoff_rolling: float
    static_net_cost: float
    rolling_net_cost: float
    net_savings: float
    savings_pct: float
    num_rolls: float          # float to support averaged results
    final_spot: float
    month_details: list[dict] = field(default_factory=list)


def simulate_single_loan(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    start_date: pd.Timestamp,
    ltv: float = 0.70,
    loan_tenor_months: int = 12,
    loan_rate: float = 0.10,
    payments_per_year: int = 12,
    min_roll_profit: float = 200.0,
    r: float = 0.0,
    cutoff_date: pd.Timestamp | None = None,
    iv_tables: dict[int, pd.DataFrame] | None = None,
) -> LoanResult:
    """Simulate one loan with static-vs-rolling PUT comparison.

    Args:
        daily_prices: Daily BTC prices (real, or real+GBM extension).
        surface: IV surface DataFrame (multi-index: date, ttm_days, mny).
        start_date: Loan origination date.
        cutoff_date: Dates after this use RV-based IV lookup instead of
            direct surface lookup. None = always use surface (Tier 1).
        iv_tables: Per-tenor weekly IV tables for RV-based lookup.
            Required when cutoff_date is set. Built by build_iv_tables().
    """
    # ── Month 0: Origination ──
    s0 = nearest_price(daily_prices, start_date)
    d0 = ltv * s0
    amort = build_amortisation_schedule(d0, loan_rate, 1, payments_per_year)

    iv0 = lookup_iv(surface, start_date, 365, d0 / s0)
    initial_premium = bs_price(s0, d0, 1.0, r, iv0, call=False)

    K_held = d0
    held_expiry_date = start_date + pd.Timedelta(days=365)
    K_static = d0
    roll_profits: list[float] = []
    month_details: list[dict] = []

    # ── Months 1–11: Evaluate rolls ──
    for month in range(1, loan_tenor_months):
        current_date = start_date + pd.DateOffset(months=month)
        st = nearest_price(daily_prices, current_date)
        dt = amort[month]
        remaining_months = loan_tenor_months - month

        tenor_days = map_tenor_bucket(remaining_months)

        # ── IV lookup: surface (real months) vs RV-based (simulated months) ──
        use_rv = (cutoff_date is not None and iv_tables is not None
                  and current_date > cutoff_date and tenor_days in iv_tables)

        if use_rv:
            rv = compute_rv_from_prices(daily_prices, current_date)
            iv_held = lookup_iv_weekly(iv_tables[tenor_days], rv, K_held / st)
            iv_repl = lookup_iv_weekly(iv_tables[tenor_days], rv, dt / st)
        else:
            iv_held = lookup_iv(surface, current_date, tenor_days, K_held / st)
            iv_repl = lookup_iv(surface, current_date, tenor_days, dt / st)

        # Price held PUT
        held_days_left = max((held_expiry_date - current_date).days, 1)
        held_value = bs_price(st, K_held, held_days_left / 365.0, r, iv_held,
                              call=False)

        # Price replacement PUT
        replacement_tenor = tenor_days / 365.0
        replacement_cost = bs_price(st, dt, replacement_tenor, r, iv_repl,
                                    call=False)

        profit = held_value - replacement_cost
        rolled = profit >= min_roll_profit

        month_details.append({
            "month": month,
            "date": str(current_date.date()),
            "spot": round(st, 2),
            "debt": round(dt, 2),
            "K_held": round(K_held, 2),
            "held_value": round(held_value, 2),
            "replacement_cost": round(replacement_cost, 2),
            "roll_profit": round(profit, 2),
            "rolled": rolled,
        })

        if rolled:
            roll_profits.append(profit)
            K_held = dt
            held_expiry_date = current_date + pd.Timedelta(days=tenor_days)

    # ── Month 12: Expiration ──
    final_date = start_date + pd.DateOffset(months=loan_tenor_months)
    s_final = nearest_price(daily_prices, final_date)

    tp_static = max(K_static - s_final, 0.0)
    tp_rolling = max(K_held - s_final, 0.0)
    total_rp = sum(roll_profits)

    static_net = initial_premium - tp_static
    rolling_net = initial_premium - total_rp - tp_rolling
    savings = static_net - rolling_net
    savings_pct = (savings / initial_premium * 100) if initial_premium > 0 else 0.0

    return LoanResult(
        start_date=start_date,
        spot_at_start=s0,
        initial_premium=initial_premium,
        roll_profits=roll_profits,
        total_roll_profit=total_rp,
        terminal_payoff_static=tp_static,
        terminal_payoff_rolling=tp_rolling,
        static_net_cost=static_net,
        rolling_net_cost=rolling_net,
        net_savings=savings,
        savings_pct=savings_pct,
        num_rolls=len(roll_profits),
        final_spot=s_final,
        month_details=month_details,
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_mc.py::TestSimulateSingleLoan -v`
Expected: 6 passed

**Step 5: Commit**

```bash
git add bitmor_rolldown_mc.py tests/test_rolldown_mc.py
git commit -m "feat: add LoanResult dataclass and simulate_single_loan engine"
```

---

### Task 7: Tier 1 — Pure Historical Backtest

**Files:**
- Modify: `bitmor_rolldown_mc.py`
- Modify: `tests/test_rolldown_mc.py`

**Step 1: Write failing tests**

Append to `tests/test_rolldown_mc.py`:

```python
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
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_mc.py::TestTier1 -v`
Expected: FAIL — `ImportError: cannot import name 'run_tier1'`

**Step 3: Write implementation**

Append to `bitmor_rolldown_mc.py`:

```python
def run_tier1(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    backtest_years: int = 3,
    start_freq: str = "daily",
    **loan_kwargs,
) -> list[LoanResult]:
    """Tier 1: Pure historical backtest — every start date uses 100% real data."""
    last_date = daily_prices.index[-1]
    tier1_end = last_date - pd.DateOffset(years=1)
    tier1_start = last_date - pd.DateOffset(years=1 + backtest_years)

    freq_map = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}
    start_dates = pd.date_range(tier1_start, tier1_end,
                                freq=freq_map.get(start_freq, "D"))
    start_dates = start_dates[start_dates >= daily_prices.index[0]]

    # Tier 1: all months are historical → no RV-based lookup needed
    results: list[LoanResult] = []
    for sd in start_dates:
        try:
            results.append(simulate_single_loan(daily_prices, surface, sd,
                                                cutoff_date=None, iv_tables=None,
                                                **loan_kwargs))
        except (ValueError, KeyError) as e:
            logging.warning("Tier 1 skipping %s: %s", sd.date(), e)

    logging.info("Tier 1: %d loans evaluated", len(results))
    return results
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_mc.py::TestTier1 -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add bitmor_rolldown_mc.py tests/test_rolldown_mc.py
git commit -m "feat: add Tier 1 pure historical backtest"
```

---

### Task 8: Tier 2 — Recent Loans with Simulated Tails

**Files:**
- Modify: `bitmor_rolldown_mc.py`
- Modify: `tests/test_rolldown_mc.py`

**Step 1: Write failing tests**

Append to `tests/test_rolldown_mc.py`:

```python
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
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_mc.py::TestAverageResults tests/test_rolldown_mc.py::TestTier2 -v`
Expected: FAIL — `ImportError`

**Step 3: Write implementation**

Append to `bitmor_rolldown_mc.py`:

```python
def average_results(results: list[LoanResult]) -> LoanResult:
    """Average numeric fields across MC path results for one start date."""
    n = len(results)
    return LoanResult(
        start_date=results[0].start_date,
        spot_at_start=results[0].spot_at_start,
        initial_premium=results[0].initial_premium,
        roll_profits=[],
        total_roll_profit=sum(r.total_roll_profit for r in results) / n,
        terminal_payoff_static=sum(r.terminal_payoff_static for r in results) / n,
        terminal_payoff_rolling=sum(r.terminal_payoff_rolling for r in results) / n,
        static_net_cost=sum(r.static_net_cost for r in results) / n,
        rolling_net_cost=sum(r.rolling_net_cost for r in results) / n,
        net_savings=sum(r.net_savings for r in results) / n,
        savings_pct=sum(r.savings_pct for r in results) / n,
        num_rolls=sum(r.num_rolls for r in results) / n,
        final_spot=sum(r.final_spot for r in results) / n,
    )


def run_tier2(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    n_mc_paths: int = 1000,
    start_freq: str = "daily",
    mu: float = 0.0,
    sigma: float = 0.5,
    seed: int | None = None,
    iv_tables: dict[int, pd.DataFrame] | None = None,
    **loan_kwargs,
) -> list[LoanResult]:
    """Tier 2: Recent loans — real data up to today, GBM tails for remaining months.

    Months within real data use direct surface lookup; simulated tail months
    use RV-based IV lookup via iv_tables.
    """
    last_date = daily_prices.index[-1]
    tier2_start = last_date - pd.DateOffset(years=1)

    freq_map = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}
    start_dates = pd.date_range(tier2_start, last_date,
                                freq=freq_map.get(start_freq, "D"))
    start_dates = start_dates[start_dates >= daily_prices.index[0]]

    rng = np.random.default_rng(seed)
    loan_tenor = loan_kwargs.get("loan_tenor_months", 12)

    results: list[LoanResult] = []
    for sd in start_dates:
        end_needed = sd + pd.DateOffset(months=loan_tenor)
        path_results: list[LoanResult] = []

        for _ in range(n_mc_paths):
            if end_needed > last_date:
                days_forward = (end_needed - last_date).days + 30
                spot_at_cutoff = float(daily_prices.iloc[-1])
                gbm = generate_gbm_path(spot_at_cutoff, mu, sigma,
                                        days_forward, rng)
                gbm_dates = pd.date_range(last_date + pd.Timedelta(days=1),
                                          periods=days_forward, freq="D")
                extended = pd.concat([
                    daily_prices,
                    pd.Series(gbm[1:], index=gbm_dates, name="close"),
                ])
            else:
                extended = daily_prices

            try:
                path_results.append(
                    simulate_single_loan(extended, surface, sd,
                                         cutoff_date=last_date,
                                         iv_tables=iv_tables,
                                         **loan_kwargs))
            except (ValueError, KeyError):
                continue

        if path_results:
            results.append(average_results(path_results))

    logging.info("Tier 2: %d start dates evaluated (%d paths each)",
                 len(results), n_mc_paths)
    return results
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_mc.py::TestAverageResults tests/test_rolldown_mc.py::TestTier2 -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add bitmor_rolldown_mc.py tests/test_rolldown_mc.py
git commit -m "feat: add Tier 2 recent loans with simulated GBM tails"
```

---

### Task 9: Tier 3 — Forward MC from Today

**Files:**
- Modify: `bitmor_rolldown_mc.py`
- Modify: `tests/test_rolldown_mc.py`

**Step 1: Write failing tests**

Append to `tests/test_rolldown_mc.py`:

```python
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
        """All paths start from same spot → same initial premium."""
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
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_mc.py::TestTier3 -v`
Expected: FAIL — `ImportError`

**Step 3: Write implementation**

Append to `bitmor_rolldown_mc.py`:

```python
def run_tier3(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    n_forward_paths: int = 1000,
    mu: float = 0.0,
    sigma: float = 0.5,
    seed: int | None = None,
    iv_tables: dict[int, pd.DataFrame] | None = None,
    **loan_kwargs,
) -> list[LoanResult]:
    """Tier 3: Forward MC — full GBM paths from today's spot price.

    All months are simulated, so all use RV-based IV lookup.
    """
    last_date = daily_prices.index[-1]
    spot_today = float(daily_prices.iloc[-1])
    loan_tenor = loan_kwargs.get("loan_tenor_months", 12)

    rng = np.random.default_rng(seed)
    n_days = loan_tenor * 31 + 30  # enough days to cover loan

    results: list[LoanResult] = []
    for _ in range(n_forward_paths):
        gbm = generate_gbm_path(spot_today, mu, sigma, n_days, rng)
        gbm_dates = pd.date_range(last_date, periods=n_days + 1, freq="D")
        path_prices = pd.Series(gbm, index=gbm_dates, name="close")

        try:
            results.append(
                simulate_single_loan(path_prices, surface, last_date,
                                     cutoff_date=last_date,
                                     iv_tables=iv_tables,
                                     **loan_kwargs))
        except (ValueError, KeyError) as e:
            logging.warning("Tier 3 path skipped: %s", e)

    logging.info("Tier 3: %d forward paths evaluated", len(results))
    return results
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_mc.py::TestTier3 -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add bitmor_rolldown_mc.py tests/test_rolldown_mc.py
git commit -m "feat: add Tier 3 forward MC from today's price"
```

---

### Task 10: CLI, Reporting & CSV Output

**Files:**
- Modify: `bitmor_rolldown_mc.py`
- Modify: `tests/test_rolldown_mc.py`

**Step 1: Write failing tests**

Append to `tests/test_rolldown_mc.py`:

```python
from bitmor_rolldown_mc import format_tier_report, save_tier_csv


class TestFormatReport:
    def test_report_contains_stats(self, synthetic_prices, synthetic_surface):
        results = run_tier1(synthetic_prices, synthetic_surface,
                            backtest_years=1, start_freq="monthly")
        report = format_tier_report(results, "Test Tier")
        assert "Test Tier" in report
        assert "Avg initial PUT premium" in report
        assert "Avg net savings" in report

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
        assert "net_savings" in df.columns
        assert "terminal_delta" in df.columns
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_mc.py::TestFormatReport tests/test_rolldown_mc.py::TestSaveTierCSV -v`
Expected: FAIL — `ImportError`

**Step 3: Write implementation**

Append to `bitmor_rolldown_mc.py`:

```python
import argparse
import datetime as dt


def format_tier_report(results: list[LoanResult], title: str) -> str:
    """Format tier results into a printable report string."""
    if not results:
        return f"\n=== {title}: No results ==="

    n = len(results)
    avg = lambda attr: sum(getattr(r, attr) for r in results) / n
    savings_list = sorted(r.net_savings for r in results)
    dates = [r.start_date for r in results]
    date_range = (f"{min(dates).strftime('%Y-%m-%d')} to "
                  f"{max(dates).strftime('%Y-%m-%d')}")

    avg_prem = avg("initial_premium")
    avg_sav = avg("net_savings")
    avg_pct = (avg_sav / avg_prem * 100) if avg_prem > 0 else 0

    lines = [
        f"\n=== {title} ({n} loans, {date_range}) ===",
        f"  Avg initial PUT premium        : ${avg_prem:,.2f}",
        f"  Avg \u03a3 roll profits             : ${avg('total_roll_profit'):,.2f}",
        f"  Avg terminal payoff (static)   : ${avg('terminal_payoff_static'):,.2f}",
        f"  Avg terminal payoff (rolling)  : ${avg('terminal_payoff_rolling'):,.2f}",
        f"  Avg net savings                : ${avg_sav:,.2f} ({avg_pct:.1f}% of premium)",
        f"  Median net savings             : ${savings_list[n // 2]:,.2f}",
        f"  Range                          : ${savings_list[0]:,.2f} to ${savings_list[-1]:,.2f}",
        f"  Avg rolls per loan             : {avg('num_rolls'):.1f}",
        f"  % loans where rolling helped   : {sum(1 for r in results if r.net_savings > 0) / n * 100:.1f}%",
    ]
    return "\n".join(lines)


def format_tier3_report(results: list[LoanResult], spot_today: float) -> str:
    """Format Tier 3 report with percentiles."""
    base = format_tier_report(results, f"Tier 3: Forward MC from Today "
                              f"({len(results)} paths, spot = ${spot_today:,.2f})")
    if not results:
        return base

    savings = [r.net_savings for r in results]
    pcts = np.percentile(savings, [5, 25, 50, 75, 95])
    base += (f"\n  Percentiles (5/25/50/75/95)    : "
             f"${pcts[0]:,.2f} / ${pcts[1]:,.2f} / ${pcts[2]:,.2f} / "
             f"${pcts[3]:,.2f} / ${pcts[4]:,.2f}")
    return base


def save_tier_csv(results: list[LoanResult], filepath: str) -> None:
    """Save per-loan/per-path results to CSV."""
    rows = []
    for r in results:
        rows.append({
            "start_date": r.start_date.strftime("%Y-%m-%d"),
            "spot": round(r.spot_at_start, 2),
            "initial_premium": round(r.initial_premium, 2),
            "roll_profits": round(r.total_roll_profit, 2),
            "terminal_payoff_static": round(r.terminal_payoff_static, 2),
            "terminal_payoff_rolling": round(r.terminal_payoff_rolling, 2),
            "terminal_delta": round(r.terminal_payoff_rolling - r.terminal_payoff_static, 2),
            "net_savings": round(r.net_savings, 2),
            "savings_pct": round(r.savings_pct, 2),
            "num_rolls": (int(r.num_rolls) if r.num_rolls == int(r.num_rolls)
                          else round(r.num_rolls, 1)),
            "final_spot": round(r.final_spot, 2),
        })
    pd.DataFrame(rows).to_csv(filepath, index=False)
    logging.info("Saved %d rows to %s", len(rows), filepath)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bitmor PUT Roll-Down Cost Reduction Simulator")
    p.add_argument("--surface", default="btc_iv_surface_svi.csv",
                   help="Path to SVI IV surface CSV")
    p.add_argument("--price", default="BTCUSDT_1h.csv",
                   help="Path to hourly BTC price CSV")
    p.add_argument("--ltv", type=float, default=0.70)
    p.add_argument("--loan_tenor_months", type=int, default=12)
    p.add_argument("--loan_rate", type=float, default=0.10)
    p.add_argument("--payments_per_year", type=int, default=12)
    p.add_argument("--min_roll_profit", type=float, default=200.0)
    p.add_argument("--r", type=float, default=0.0, help="Risk-free rate")
    p.add_argument("--backtest_years", type=int, default=3)
    p.add_argument("--start_freq", default="daily",
                   choices=["daily", "weekly", "monthly"])
    p.add_argument("--n_mc_paths", type=int, default=1000,
                   help="MC paths per start date (Tier 2)")
    p.add_argument("--n_forward_paths", type=int, default=1000,
                   help="Full forward MC paths (Tier 3)")
    p.add_argument("--seed", type=int, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    surface = load_surface(args.surface)
    price_hourly = load_price(args.price)
    daily_prices = price_hourly.resample("1D").last().dropna()

    mu, sigma = calibrate_hist_mu_sigma(price_hourly)
    logging.info("Calibrated GBM: mu=%.4f, sigma=%.4f", mu, sigma)

    # Build per-tenor IV tables for RV-based lookup during simulated months
    tenor_days_needed = [90, 180, 270, 365]
    iv_tables = build_iv_tables(surface, daily_prices, tenor_days_needed)
    logging.info("Built IV tables for tenors: %s", list(iv_tables.keys()))

    loan_kwargs = dict(
        ltv=args.ltv,
        loan_tenor_months=args.loan_tenor_months,
        loan_rate=args.loan_rate,
        payments_per_year=args.payments_per_year,
        min_roll_profit=args.min_roll_profit,
        r=args.r,
    )

    today = dt.date.today().strftime("%Y%m%d")

    # ── Tier 1 (all historical — no RV tables needed) ──
    tier1 = run_tier1(daily_prices, surface, args.backtest_years,
                      args.start_freq, **loan_kwargs)
    print(format_tier_report(tier1, "Tier 1: Pure Historical"))
    save_tier_csv(tier1, f"result/rolldown_tier1_{today}.csv")

    # ── Tier 2 (real data up to today, RV-based IV for simulated tail) ──
    tier2 = run_tier2(daily_prices, surface, args.n_mc_paths, args.start_freq,
                      mu, sigma, args.seed, iv_tables=iv_tables, **loan_kwargs)
    print(format_tier_report(tier2, "Tier 2: Recent + Simulated"))
    save_tier_csv(tier2, f"result/rolldown_tier2_{today}.csv")

    # ── Tier 3 (full GBM, all months use RV-based IV) ──
    spot_today = float(daily_prices.iloc[-1])
    tier3 = run_tier3(daily_prices, surface, args.n_forward_paths,
                      mu, sigma, args.seed, iv_tables=iv_tables, **loan_kwargs)
    print(format_tier3_report(tier3, spot_today))
    save_tier_csv(tier3, f"result/rolldown_tier3_{today}.csv")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_mc.py::TestFormatReport tests/test_rolldown_mc.py::TestSaveTierCSV -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add bitmor_rolldown_mc.py tests/test_rolldown_mc.py
git commit -m "feat: add CLI, reporting, and CSV output for rolldown simulator"
```

---

### Task 11: IV Pipeline Extension

**Files:**
- Modify: `btc_iv.py`
- Modify: `iv_surface_svi.py`

This task extends the data pipeline to fetch and calibrate longer-dated option data. The code changes are small; the actual data fetch is a long-running step (hours) that runs separately.

**Step 1: Write failing test for quarterly expiry helper**

Append to `tests/test_rolldown_utils.py` (we test the helper in isolation):

```python
import datetime as _dt
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
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
```

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rolldown_utils.py::TestQuarterlyExpiries -v`
Expected: FAIL — `ImportError: cannot import name 'quarterly_expiries' from 'btc_iv'`

**Step 3: Add quarterly_expiries to btc_iv.py**

Add this function to `btc_iv.py` (after the existing `month_end_expiry` function):

```python
def _last_friday(year: int, month: int) -> dt.date:
    """Last Friday of a given month."""
    # Start from last day of month, walk back to Friday
    if month == 12:
        last_day = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        last_day = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    offset = (last_day.weekday() - 4) % 7  # days since Friday
    return last_day - dt.timedelta(days=offset)


def quarterly_expiries(ref_date: dt.date) -> list[dt.date]:
    """Return the next 4 quarterly (Mar/Jun/Sep/Dec) last-Fridays after ref_date."""
    quarter_months = [3, 6, 9, 12]
    candidates: list[dt.date] = []
    for year in [ref_date.year, ref_date.year + 1, ref_date.year + 2]:
        for m in quarter_months:
            exp = _last_friday(year, m)
            if exp > ref_date:
                candidates.append(exp)
    candidates.sort()
    return candidates[:4]
```

Then modify the `main()` function's daily loop to also collect surfaces for quarterly expiry instruments. In the loop where `collect_surface(day, instruments)` is called, add a second call targeting quarterly expiry instruments:

```python
# Inside main() daily loop, after the existing month-end collection:
for q_exp in quarterly_expiries(day):
    q_instruments = [i for i in instruments
                     if i.get("expiration_timestamp")
                     and dt.datetime.fromtimestamp(
                         i["expiration_timestamp"] / 1000).date() == q_exp]
    if q_instruments:
        q_df = collect_surface(day, q_instruments)
        if q_df is not None and not q_df.empty:
            append_csv(q_df, csv_file)
```

**Step 4: Extend TTM_GRID in iv_surface_svi.py**

Change line 25 of `iv_surface_svi.py`:

```python
# Before:
TTM_GRID = np.arange(15, 61)  # calendar days

# After:
TTM_GRID = np.sort(np.concatenate([np.arange(15, 61), [90, 180, 270, 365]]))
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_rolldown_utils.py::TestQuarterlyExpiries -v`
Expected: 4 passed

**Step 6: Commit**

```bash
git add btc_iv.py iv_surface_svi.py tests/test_rolldown_utils.py
git commit -m "feat: extend IV pipeline for quarterly tenors (90/180/270/365 days)"
```

**Step 7: Re-run IV pipeline (long-running, do separately)**

```bash
# This fetches ~3 years of quarterly option data from Deribit and takes hours.
# Run in a tmux/screen session:
python btc_iv.py
python iv_surface_svi.py
```

---

### Task 12: Integration Test with Real Data

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test (requires real data files)**

```python
# tests/test_integration.py
"""Integration tests — require real data files in the project root.

Skip automatically if data files are missing.
"""
import os

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
        from liquidation_utils import load_price, load_surface
        self.surface = load_surface(SURFACE)
        self.daily_prices = load_price(PRICE).resample("1D").last().dropna()

    def test_single_loan_real_data(self):
        from bitmor_rolldown_mc import simulate_single_loan
        result = simulate_single_loan(
            self.daily_prices, self.surface,
            start_date=pd.Timestamp("2023-06-01"),
        )
        assert result.initial_premium > 0
        assert result.spot_at_start > 0
        assert len(result.month_details) == 11

    def test_tier1_monthly_real_data(self):
        from bitmor_rolldown_mc import run_tier1
        results = run_tier1(
            self.daily_prices, self.surface,
            backtest_years=1, start_freq="monthly",
        )
        assert len(results) > 0

    def test_tier3_small_real_data(self):
        from bitmor_rolldown_mc import run_tier3
        from liquidation_utils import calibrate_hist_mu_sigma, load_price
        price_hourly = load_price(PRICE)
        mu, sigma = calibrate_hist_mu_sigma(price_hourly)
        results = run_tier3(
            self.daily_prices, self.surface,
            n_forward_paths=5, mu=mu, sigma=sigma, seed=42,
        )
        assert len(results) == 5
```

**Step 2: Run integration tests**

Run: `python -m pytest tests/test_integration.py -v`
Expected: PASS (or SKIP if data files not present)

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for rolldown simulator with real data"
```

---

## Summary

| Task | File(s) | What |
|------|---------|------|
| 1 | `tests/conftest.py` | Shared test fixtures |
| 2 | `rolldown_utils.py`, `tests/test_rolldown_utils.py` | Tenor bucket mapping |
| 3 | `rolldown_utils.py`, `tests/test_rolldown_utils.py` | IV surface lookup |
| 4 | `rolldown_utils.py`, `tests/test_rolldown_utils.py` | Price lookup + GBM path + RV computation + IV table builder |
| 5 | `rolldown_utils.py`, `tests/test_rolldown_utils.py` | Roll evaluation |
| 6 | `bitmor_rolldown_mc.py`, `tests/test_rolldown_mc.py` | LoanResult + simulate_single_loan (with cutoff_date/iv_tables) |
| 7 | `bitmor_rolldown_mc.py`, `tests/test_rolldown_mc.py` | Tier 1 historical backtest |
| 8 | `bitmor_rolldown_mc.py`, `tests/test_rolldown_mc.py` | Tier 2 recent + simulated |
| 9 | `bitmor_rolldown_mc.py`, `tests/test_rolldown_mc.py` | Tier 3 forward MC |
| 10 | `bitmor_rolldown_mc.py`, `tests/test_rolldown_mc.py` | CLI + reporting + CSV |
| 11 | `btc_iv.py`, `iv_surface_svi.py` | IV pipeline extension |
| 12 | `tests/test_integration.py` | Integration test |

**Dependencies:** Tasks 2–5 are independent (can run in parallel). Task 6 depends on 2–5. Tasks 7–9 depend on 6. Task 10 depends on 7–9. Task 11 is independent. Task 12 depends on all.

**Run the full simulator after all tasks:**

```bash
python bitmor_rolldown_mc.py \
  --surface btc_iv_surface_svi.csv \
  --price BTCUSDT_1h.csv \
  --start_freq monthly \
  --n_mc_paths 100 \
  --n_forward_paths 100 \
  --seed 42
```
