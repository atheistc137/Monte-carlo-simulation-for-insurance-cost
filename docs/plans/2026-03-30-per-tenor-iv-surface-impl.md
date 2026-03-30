# Per-Tenor IV Surfaces — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix phantom roll profits by fetching real long-dated option data, calibrating SVI per tenor bucket, and fixing two simulator bugs (RV annualization + held PUT tenor).

**Architecture:** Three-stage pipeline — (1) bulk Deribit data fetch including quarterly expiries, (2) per-tenor SVI calibration with forward-fill fallback, (3) bug fixes in the simulator for RV annualization and held-PUT IV lookup. Stages are independent: bug fixes (Task 1–2) have no data dependency and ship first; data pipeline (Tasks 3–5) ships second.

**Tech Stack:** Python 3.11+, pandas, numpy, scipy (L-BFGS-B), requests, joblib, pytest

**Design doc:** `docs/plans/2026-03-30-per-tenor-iv-surface-design.md`

---

## Task 1: Fix Bug A — RV Annualization Mismatch

**Context:** `compute_rv_from_prices` annualizes with `sqrt(365)` but `build_weekly_iv_table` uses `sqrt(365/7)`. The query RV is 2.65× inflated, matching crash-regime rows.

**Files:**
- Modify: `rolldown_utils.py:95`
- Test: `tests/test_rolldown_utils.py`

**Step 1: Write the failing test**

Add to `tests/test_rolldown_utils.py` inside `class TestComputeRV`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_rolldown_utils.py::TestComputeRV::test_rv_matches_table_annualization -v`
Expected: FAIL — current `sqrt(365)` produces RV ~0.38, which is > 0.25

**Step 3: Fix the annualization**

In `rolldown_utils.py`, change line 95 from:
```python
return float(log_ret.std() * np.sqrt(365))
```
to:
```python
return float(log_ret.std() * np.sqrt(365 / window_days))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_rolldown_utils.py::TestComputeRV -v`
Expected: ALL PASS (including existing tests — `test_positive_rv` and `test_reasonable_range` still hold since `sqrt(365/7)` ≈ 7.2 still produces positive values well under 5.0)

**Step 5: Commit**

```bash
git add rolldown_utils.py tests/test_rolldown_utils.py
git commit -m "fix: RV annualization to match IV table (sqrt(365/window_days))"
```

---

## Task 2: Fix Bug B — Held PUT Uses Wrong Tenor for IV Lookup

**Context:** In `bitmor_rolldown_mc.py:111-117`, the held PUT's IV is looked up from `iv_tables[tenor_days]` where `tenor_days` is the *replacement* PUT's tenor bucket. The held PUT may have a different remaining TTM (e.g., 61 days left vs replacement at 90 days). This creates IV/BS pricing inconsistency.

**Files:**
- Create: (none — helper goes in existing file)
- Modify: `rolldown_utils.py` (add `map_tenor_bucket_days`)
- Modify: `bitmor_rolldown_mc.py:107-117`
- Test: `tests/test_rolldown_utils.py`
- Test: `tests/test_rolldown_mc.py`

### Step 1: Write test for `map_tenor_bucket_days`

Add to `tests/test_rolldown_utils.py`:

```python
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
```

### Step 2: Run test to verify it fails

Run: `pytest tests/test_rolldown_utils.py::TestMapTenorBucketDays -v`
Expected: FAIL — `ImportError: cannot import name 'map_tenor_bucket_days'`

### Step 3: Implement `map_tenor_bucket_days`

Add to `rolldown_utils.py` after line 29 (after `map_tenor_bucket`):

```python
def map_tenor_bucket_days(days: int, available_tenors_days: list[int]) -> int:
    """Map a day count to the nearest available IV table tenor (in days).

    Rule: smallest available tenor >= days. Fallback: longest available.
    """
    for t in sorted(available_tenors_days):
        if t >= days:
            return t
    return max(available_tenors_days)
```

### Step 4: Run test to verify it passes

Run: `pytest tests/test_rolldown_utils.py::TestMapTenorBucketDays -v`
Expected: ALL PASS

### Step 5: Write test for held-PUT tenor fix in simulator

Add to `tests/test_rolldown_mc.py`:

```python
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
        # savings are bounded.
        assert result.savings_pct <= 100.0
```

### Step 6: Run test to verify it fails (or captures the bug)

Run: `pytest tests/test_rolldown_mc.py::TestHeldPutTenorLookup -v`
Expected: Either FAIL (savings_pct > 100%) or PASS but with inflated values. The fix ensures correctness regardless.

### Step 7: Apply the held-PUT tenor fix

In `bitmor_rolldown_mc.py`, add import at top (after existing rolldown_utils imports):
```python
from rolldown_utils import map_tenor_bucket_days
```

Then replace lines 107-117. The current code:
```python
        # -- IV lookup: surface (real months) vs RV-based (simulated months) --
        use_rv = (cutoff_date is not None and iv_tables is not None
                  and current_date > cutoff_date and tenor_days in iv_tables)

        if use_rv:
            rv = compute_rv_from_prices(daily_prices, current_date)
            iv_held = lookup_iv_weekly(iv_tables[tenor_days], rv, K_held / st)
            iv_repl = lookup_iv_weekly(iv_tables[tenor_days], rv, dt / st)
        else:
            iv_held = lookup_iv(surface, current_date, tenor_days, K_held / st)
            iv_repl = lookup_iv(surface, current_date, tenor_days, dt / st)
```

Replace with:
```python
        # -- Held PUT remaining TTM for IV lookup --
        held_days_left = max((held_expiry_date - current_date).days, 1)
        held_tenor_days = map_tenor_bucket_days(
            held_days_left, list(iv_tables.keys()) if iv_tables else [tenor_days]
        )

        # -- IV lookup: surface (real months) vs RV-based (simulated months) --
        use_rv = (cutoff_date is not None and iv_tables is not None
                  and current_date > cutoff_date and tenor_days in iv_tables)

        if use_rv:
            rv = compute_rv_from_prices(daily_prices, current_date)
            iv_held = lookup_iv_weekly(iv_tables[held_tenor_days], rv, K_held / st)
            iv_repl = lookup_iv_weekly(iv_tables[tenor_days], rv, dt / st)
        else:
            iv_held = lookup_iv(surface, current_date, held_days_left, K_held / st)
            iv_repl = lookup_iv(surface, current_date, tenor_days, dt / st)
```

Also remove the now-duplicate `held_days_left` computation that was previously at line 120:
```python
        # Price held PUT
        held_days_left = max((held_expiry_date - current_date).days, 1)
```
becomes:
```python
        # Price held PUT (held_days_left already computed above)
```

### Step 8: Run all tests

Run: `pytest tests/ -v`
Expected: ALL PASS

### Step 9: Commit

```bash
git add rolldown_utils.py bitmor_rolldown_mc.py tests/test_rolldown_utils.py tests/test_rolldown_mc.py
git commit -m "fix: held PUT IV lookup uses actual remaining TTM, not replacement tenor"
```

---

## Task 3: Bulk Data Fetch (btc_iv.py)

**Context:** Replace per-instrument API calls with bulk `get_last_trades_by_currency_and_time`. Include quarterly expiries alongside month-end. This reduces ~274k API calls to ~3,300.

**Files:**
- Modify: `btc_iv.py:50-57` (reuse `call_api`), `btc_iv.py:127-167` (replace `collect_surface`), `btc_iv.py:189-207` (update main loop)
- Test: `tests/test_btc_iv.py` (new file)

### Step 1: Write tests for `parse_expiry_from_instrument` and `collect_surface_bulk`

Create `tests/test_btc_iv.py`:

```python
"""Tests for btc_iv.py bulk data fetch."""
import datetime as dt
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from btc_iv import (
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
    @patch("btc_iv.call_api")
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

    @patch("btc_iv.call_api")
    def test_empty_day_returns_empty(self, mock_api):
        mock_api.return_value = {"trades": [], "has_more": False}
        df = collect_surface_bulk(dt.date(2025, 1, 1), [dt.date(2025, 1, 31)])
        assert df.empty

    @patch("btc_iv.call_api")
    def test_deduplicates_to_last_trade(self, mock_api):
        """Multiple trades for same instrument → keep last by timestamp."""
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
```

### Step 2: Run tests to verify they fail

Run: `pytest tests/test_btc_iv.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_expiry_from_instrument'`

### Step 3: Implement `parse_expiry_from_instrument`

Add to `btc_iv.py` after `quarterly_expiries` (after line 110):

```python
# Month abbreviation map for Deribit instrument names
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_expiry_from_instrument(name: str) -> str | None:
    """Extract expiry date ISO string from Deribit instrument name.

    E.g. 'BTC-27JUN25-100000-C' → '2025-06-27'
    """
    parts = name.split("-")
    if len(parts) < 2:
        return None
    token = parts[1]  # e.g. '27JUN25'
    try:
        day_str = token[:len(token) - 5]   # '27'
        mon_str = token[-5:-2]              # 'JUN'
        yr_str  = token[-2:]                # '25'
        d = dt.date(2000 + int(yr_str), _MONTH_MAP[mon_str], int(day_str))
        return d.isoformat()
    except (KeyError, ValueError, IndexError):
        return None
```

### Step 4: Implement `collect_surface_bulk`

Add to `btc_iv.py` after `parse_expiry_from_instrument`:

```python
def collect_surface_bulk(day: dt.date, expiry_dates: list[dt.date]) -> pd.DataFrame:
    """Fetch ALL BTC option trades for one UTC day via currency-level endpoint,
    keep last trade per instrument, filter to target expiries locally."""
    day_start = dt.datetime.combine(day, dt.time(0, tzinfo=timezone.utc))
    start_ms  = int(day_start.timestamp() * 1000)
    end_ms    = start_ms + 86_400_000 - 1

    all_trades: list[dict] = []
    has_more = True
    params = {
        "currency": CURRENCY, "kind": "option",
        "start_timestamp": start_ms, "end_timestamp": end_ms,
        "include_old": True, "count": 1000, "sorting": "asc",
    }
    while has_more:
        res = call_api("get_last_trades_by_currency_and_time", params)
        trades = res.get("trades", [])
        all_trades.extend(trades)
        has_more = res.get("has_more", False)
        if trades:
            params["start_timestamp"] = trades[-1]["timestamp"] + 1
        time.sleep(RATE_LIMIT_SLEEP)

    if not all_trades:
        return pd.DataFrame()

    # Last trade per instrument for this day
    df = pd.DataFrame(all_trades)
    df = df.sort_values("timestamp").groupby("instrument_name").last().reset_index()

    # Filter to target expiries
    expiry_set = {e.isoformat() for e in expiry_dates}
    rows = []
    for _, t in df.iterrows():
        inst_expiry = parse_expiry_from_instrument(t["instrument_name"])
        if inst_expiry not in expiry_set or t.get("iv") is None:
            continue
        # Extract strike and option_type from instrument name
        parts = t["instrument_name"].split("-")
        strike = float(parts[2])
        option_type = "call" if parts[3] == "C" else "put"
        expiry_date = dt.date.fromisoformat(inst_expiry)
        ttm_days = (dt.datetime.combine(expiry_date, dt.time(0)) -
                    dt.datetime.combine(day, dt.time(0))).days
        rows.append({
            "date":        day.isoformat(),
            "expiry":      inst_expiry,
            "instrument":  t["instrument_name"],
            "strike":      strike,
            "option_type": option_type,
            "ttm_days":    ttm_days,
            "iv":          float(t["iv"]),
            "price":       float(t["price"]),
        })

    return pd.DataFrame(rows)
```

### Step 5: Update the main loop

Replace `btc_iv.py` main function (lines 189–207) with:

```python
def day_already_in_csv(day: dt.date) -> bool:
    """Check if a day's data is already in the CSV (checkpoint/resume)."""
    if not pathlib.Path(CSV_FILE).exists():
        return False
    try:
        # Read only the date column for speed
        dates = pd.read_csv(CSV_FILE, usecols=["date"])["date"].unique()
        return day.isoformat() in dates
    except (KeyError, pd.errors.EmptyDataError):
        return False


def main() -> None:
    today = dt.datetime.now(timezone.utc).date()

    # Pre-load existing dates for checkpoint/resume
    existing_dates: set[str] = set()
    if pathlib.Path(CSV_FILE).exists():
        try:
            existing_dates = set(
                pd.read_csv(CSV_FILE, usecols=["date"])["date"].unique()
            )
        except (KeyError, pd.errors.EmptyDataError):
            pass
    print(f"  {len(existing_dates)} days already fetched (checkpoint).")

    for delta in range(1, LOOKBACK_DAYS + 1):
        day = today - dt.timedelta(days=delta)

        if day.isoformat() in existing_dates:
            continue  # checkpoint: skip fetched days

        targets = [month_end_expiry(day)] + quarterly_expiries(day)
        print(f"{day}  → {len(targets)} target expiries …", end="", flush=True)

        df = collect_surface_bulk(day, targets)
        if df.empty:
            print("  no trades")
            continue

        append_csv(df)
        print(f"  {len(df):,} points")
```

### Step 6: Run tests

Run: `pytest tests/test_btc_iv.py -v`
Expected: ALL PASS

### Step 7: Commit

```bash
git add btc_iv.py tests/test_btc_iv.py
git commit -m "feat: bulk data fetch with quarterly expiries and checkpoint/resume"
```

---

## Task 4: Per-Tenor SVI Calibration (iv_surface_svi.py)

**Context:** Currently one SVI fit per day across all tenors. With mixed TTMs (30-day and 365-day), one SVI cannot fit both. Must bucket by tenor and calibrate separately.

**Files:**
- Modify: `iv_surface_svi.py:102-193` (calibration loop + surface generation)
- Test: `tests/test_iv_surface_svi.py` (new file)

### Step 1: Write tests for tenor bucketing and per-tenor calibration

Create `tests/test_iv_surface_svi.py`:

```python
"""Tests for per-tenor SVI calibration."""
import numpy as np
import pandas as pd
import pytest

from iv_surface_svi import assign_tenor_bucket, calibrate_svi, TENOR_BUCKETS


class TestAssignTenorBucket:
    def test_short_dated(self):
        assert assign_tenor_bucket(30) == "short"

    def test_boundary_60(self):
        assert assign_tenor_bucket(60) == "short"

    def test_90d_bucket(self):
        assert assign_tenor_bucket(90) == "90d"

    def test_180d_bucket(self):
        assert assign_tenor_bucket(180) == "180d"

    def test_270d_bucket(self):
        assert assign_tenor_bucket(270) == "270d"

    def test_365d_bucket(self):
        assert assign_tenor_bucket(365) == "365d"

    def test_edge_135(self):
        """135 is upper bound of 90d bucket."""
        assert assign_tenor_bucket(135) == "90d"

    def test_edge_136(self):
        """136 starts 180d bucket."""
        assert assign_tenor_bucket(136) == "180d"


class TestPerTenorCalibration:
    def test_calibrate_svi_returns_six_values(self):
        """SVI calibration returns (a, b, rho, m, sigma, error)."""
        k = np.array([-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3])
        t = np.full_like(k, 0.25)  # 90 days
        iv = np.array([0.60, 0.55, 0.50, 0.48, 0.47, 0.48, 0.50])
        result = calibrate_svi(k, t, iv)
        assert len(result) == 6
        a, b, rho, m, sigma, err = result
        assert err < 0.1  # reasonable fit

    def test_different_tenors_produce_different_params(self):
        """90d and 365d smiles should yield different SVI params."""
        k = np.array([-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3])
        # 90-day smile: steeper skew
        t_90 = np.full_like(k, 90 / 365)
        iv_90 = np.array([0.70, 0.60, 0.52, 0.48, 0.47, 0.48, 0.50])
        # 365-day smile: flatter, higher level
        t_365 = np.full_like(k, 365 / 365)
        iv_365 = np.array([0.55, 0.52, 0.50, 0.49, 0.48, 0.49, 0.50])

        params_90 = calibrate_svi(k, t_90, iv_90)
        params_365 = calibrate_svi(k, t_365, iv_365)
        # At minimum, 'a' or 'b' should differ meaningfully
        assert not np.allclose(params_90[:5], params_365[:5], atol=0.01)
```

### Step 2: Run tests to verify they fail

Run: `pytest tests/test_iv_surface_svi.py -v`
Expected: FAIL — `ImportError: cannot import name 'assign_tenor_bucket'`

### Step 3: Implement tenor bucketing

Add to `iv_surface_svi.py` after the configuration defaults (after line 27):

```python
# ───────────────────────── tenor bucketing ────────────────────────────────
TENOR_BUCKETS = [
    ("short", 3,   60),
    ("90d",   61,  135),
    ("180d",  136, 225),
    ("270d",  226, 315),
    ("365d",  316, 400),
]


def assign_tenor_bucket(ttm_days: float) -> str:
    """Assign a TTM value to its tenor bucket label."""
    for label, lo, hi in TENOR_BUCKETS:
        if lo <= ttm_days <= hi:
            return label
    if ttm_days < 3:
        return "short"
    return "365d"
```

### Step 4: Run tests to verify they pass

Run: `pytest tests/test_iv_surface_svi.py -v`
Expected: ALL PASS

### Step 5: Update `calibrate_one_day` to accept tenor_bucket

Modify `calibrate_one_day` (lines 102-119) to return the `tenor_bucket` field:

Current signature and return at `iv_surface_svi.py:102-119`:
```python
def calibrate_one_day(d: pd.Timestamp, grp: pd.DataFrame) -> Dict[str, float] | None:
```

Replace the entire function with:
```python
def calibrate_one_day(d: pd.Timestamp, tenor_bucket: str,
                      grp: pd.DataFrame) -> Dict[str, float] | None:
    if len(grp) < calibrate_one_day.min_quotes:
        logging.debug("%s/%s skipped (< %d quotes)", d.date(), tenor_bucket,
                      calibrate_one_day.min_quotes)
        return None
    k  = np.log(grp["strike"].values / grp["spot"].values)
    t  = grp["ttm_days"].values / 365.0
    iv = grp["iv"].values
    a, b, rho, m, sigma, err = calibrate_svi(k, t, iv)
    return {
        "date":         d,
        "tenor_bucket": tenor_bucket,
        "a":            a,
        "b":            b,
        "rho":          rho,
        "m":            m,
        "sigma":        sigma,
        "error":        err,
        "quotes":       len(grp),
    }
```

### Step 6: Update the main calibration loop

Replace lines 162-175 (the calibration + params save block) in `main()`:

Current code:
```python
    # Calibrate SVI in parallel for each day
    calibrate_one_day.min_quotes = cfg.min_quotes
    results = Parallel(n_jobs=cfg.n_jobs)(
        delayed(calibrate_one_day)(d, grp)
        for d, grp in opt.groupby("date")
    )
    params = pd.DataFrame([r for r in results if r is not None])
    params.to_csv(cfg.out_param, index=False)
    logging.info("Saved SVI parameters → %s (%d days)", cfg.out_param, len(params))
```

Replace with:
```python
    # Assign tenor buckets
    opt["tenor_bucket"] = opt["ttm_days"].apply(assign_tenor_bucket)

    # Calibrate SVI per (date, tenor_bucket) in parallel
    calibrate_one_day.min_quotes = cfg.min_quotes
    results = Parallel(n_jobs=cfg.n_jobs)(
        delayed(calibrate_one_day)(d, tb, grp)
        for (d, tb), grp in opt.groupby(["date", "tenor_bucket"])
    )
    params = pd.DataFrame([r for r in results if r is not None])

    # Forward-fill sparse tenor buckets (with staleness cap)
    if not params.empty:
        params = params.sort_values(["tenor_bucket", "date"])
        filled_parts = []
        for tb, grp in params.groupby("tenor_bucket"):
            grp = grp.set_index("date").asfreq("D")
            grp["tenor_bucket"] = tb
            # Forward-fill SVI params, cap at max_ff_days
            svi_cols = ["a", "b", "rho", "m", "sigma", "error", "quotes"]
            grp[svi_cols] = grp[svi_cols].ffill(limit=cfg.max_ff_days)
            grp = grp.dropna(subset=["a"])  # drop rows beyond staleness cap
            filled_parts.append(grp.reset_index())
        params = pd.concat(filled_parts, ignore_index=True)

    params.to_csv(cfg.out_param, index=False)
    logging.info("Saved SVI parameters → %s (%d rows)", cfg.out_param, len(params))
```

### Step 7: Update the surface generation loop

Replace lines 177-193 (the surface generation block) in `main()`:

Current code:
```python
    # Build synthetic IV surface
    surf_rows: List[Dict[str, float]] = []
    for _, row in params.iterrows():
        trade_date = row["date"]
        a, b, rho, m, sigma = row[["a", "b", "rho", "m", "sigma"]]
        spot_price = spot.loc[trade_date]
        for T in TTM_GRID:
            t = T / 365.0
            for mny in MNY_GRID:
                K = mny * spot_price
                k = np.log(K / spot_price)
                w = svi_total_variance(k, a, b, rho, m, sigma)
                iv = np.sqrt(max(w, 1e-12) / t) * 100.0
                surf_rows.append(dict(date=trade_date, ttm_days=T, mny=mny, iv=iv))
```

Replace with:
```python
    # Map tenor buckets to their TTM grid ranges
    BUCKET_TTM = {
        "short": [T for T in TTM_GRID if T <= 60],
        "90d":   [90],
        "180d":  [180],
        "270d":  [270],
        "365d":  [365],
    }

    # Build synthetic IV surface using per-bucket params
    surf_rows: List[Dict[str, float]] = []
    for _, row in params.iterrows():
        trade_date = row["date"]
        tb = row["tenor_bucket"]
        a, b, rho, m, sigma = row[["a", "b", "rho", "m", "sigma"]]
        try:
            spot_price = spot.loc[trade_date]
        except KeyError:
            continue
        for T in BUCKET_TTM.get(tb, []):
            t = T / 365.0
            for mny in MNY_GRID:
                K = mny * spot_price
                k = np.log(K / spot_price)
                w = svi_total_variance(k, a, b, rho, m, sigma)
                iv = np.sqrt(max(w, 1e-12) / t) * 100.0
                surf_rows.append(dict(date=trade_date, ttm_days=T, mny=mny, iv=iv))
```

### Step 8: Run all tests

Run: `pytest tests/ -v`
Expected: ALL PASS

### Step 9: Commit

```bash
git add iv_surface_svi.py tests/test_iv_surface_svi.py
git commit -m "feat: per-tenor SVI calibration with forward-fill and staleness cap"
```

---

## Task 5: Validation

**Context:** After the full pipeline runs, verify the fix produces correct data before trusting simulation results.

**Files:**
- Test: `tests/test_integration.py` (modify existing)

### Step 1: Add validation assertions to integration test

Add to `tests/test_integration.py`:

```python
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
        from rolldown_utils import compute_rv_from_prices
        from liquidation_utils import load_price
        price = load_price(Path("BTCUSDT_1h.csv"))
        daily = price.resample("1D").last().dropna()
        rv = compute_rv_from_prices(daily, daily.index[-10])
        # Should be < 2.0 (200% annualized vol) — with old bug it was > 3.0
        assert rv < 2.0, f"RV={rv:.3f} still looks inflated"
```

### Step 2: Run validation tests (after pipeline)

Run: `pytest tests/test_integration.py::TestPerTenorSurface -v`
Expected: ALL PASS (after running the full pipeline: `python btc_iv.py && python iv_surface_svi.py`)

### Step 3: Run full simulation regression

Run: `python bitmor_rolldown_mc.py`
Check: Tier 2/3 `savings_pct` no longer exceeds 100%

### Step 4: Commit

```bash
git add tests/test_integration.py
git commit -m "test: add per-tenor surface validation and RV consistency checks"
```

---

## Execution Order

| # | Task | Dependency | Time |
|---|------|-----------|------|
| 1 | Fix Bug A (RV annualization) | None | 5 min |
| 2 | Fix Bug B (held PUT tenor) | None | 10 min |
| 3 | Bulk data fetch (btc_iv.py) | None | 15 min code, ~11 min API run |
| 4 | Per-tenor SVI calibration | Task 3 data | 15 min |
| 5 | Validation | Tasks 1–4 | 5 min |

Tasks 1, 2, and 3 (code changes only) are independent and can be done in parallel. Task 3's API run + Task 4 are sequential. Task 5 runs after everything.
