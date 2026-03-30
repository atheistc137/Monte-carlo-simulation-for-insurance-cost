# Per-Tenor IV Surfaces for Rolldown Simulator — Design

## Problem

The rolldown simulator prices 3/6/9/12-month PUTs, but the IV pipeline only
fetches month-end contracts (TTM 3–41 days). The SVI model is calibrated on
this short-dated data and extrapolates unreliably to 365-day tenors. The
RV-based IV lookup tables are built from 60-day surface data mapped to
365-day pricing (because the surface lacks longer tenors), producing IV
levels that are inconsistent with the surface IV used for initial PUT
pricing. This inconsistency creates phantom roll profits: the initial PUT
is priced at surface IV (~0.40) but valued one month later at RV-table IV
(~0.53–0.67), inflating savings beyond 100% of premium.

The root causes are:
1. **Tenor mismatch (data)**: `build_iv_tables` maps 365 → 60 (nearest
   available), but 60-day and 365-day IV smiles are structurally different.
2. **IV source switch**: month 0 uses direct surface lookup, month 1+ uses
   RV-based table lookup. With mismatched tenors, the two sources return
   very different IV levels for the same option.
3. **RV annualization mismatch (Bug A)**: `compute_rv_from_prices` uses
   `sqrt(365)` to annualize, but the IV tables are keyed by RV computed
   with `sqrt(365/7)`. The query RV is 2.65× inflated, matching against
   crash-regime rows with extreme IV.
4. **Held PUT tenor mismatch (Bug B)**: The held PUT's IV is looked up
   from the replacement PUT's tenor bucket, not its actual remaining TTM.
   This creates pricing inconsistency with the BS model which correctly
   uses `held_days_left`.

Tier 1 (pure historical) is unaffected because it uses the same surface
lookup for both initial and monthly pricing (Bugs A and B only fire when
`use_rv=True`, i.e. Tier 2/3 simulated months).

## Design Goal

IV must respond to market conditions on simulated paths: crash paths should
see higher IV than calm paths. This rules out freezing the surface or
hardcoding IV values. The solution must use real market data at the correct
tenor for each option being priced.

## Architecture: Three-Stage Pipeline

```
Stage 1: btc_iv.py (data fetch)
  Fetch month-end contracts (existing, TTM 3–41 days)
  + Fetch quarterly expiry contracts (TTM ~90/180/270/365 days)
  → btc_iv_surface2.csv (raw trades with real long-dated TTMs)

Stage 2: iv_surface_svi.py (per-tenor SVI calibration)
  Bucket raw data by (date, tenor_bucket)
  Calibrate separate SVI per (date, tenor_bucket)
  → btc_svi_params.csv (gains tenor_bucket column)
  → btc_iv_surface_svi.csv (surface with real 90/180/270/365 tenors)

Stage 3: rolldown simulator (consumption)
  build_iv_tables() finds exact tenor matches (90→90, 365→365)
  RV-based lookups use correctly-tenored data
  No more 365→60 fallback mapping
```

## Stage 1: Data Fetch (btc_iv.py)

### Current Behaviour

`collect_surface(day, instruments)` hard-codes `month_end_expiry(day)` as
the target expiry. The main loop calls this once per day, making one API
call per instrument matching that expiry (`get_last_trades_by_instrument_and_time`).
With quarterly expiries added naively this becomes
1,095 days × ~5 expiries × ~50 instruments ≈ 274k API calls × 0.2s ≈ 15 hours.

**Existing code to reuse**: `quarterly_expiries(day)` already exists (line
100–110 of `btc_iv.py`) but is never called from the main loop.

### Changes

1. **Replace per-instrument fetch with bulk currency-level endpoint**.
   Deribit's `get_last_trades_by_currency_and_time` returns *all* BTC option
   trades within a time window in one paginated response. Instead of asking
   "did this specific instrument trade?" 250 times per day, we ask "what
   BTC options traded today?" once, then filter locally.

   New function `collect_surface_bulk(day, expiry_dates)` replaces the
   existing `collect_surface`:

```python
def collect_surface_bulk(day: dt.date, expiry_dates: list[dt.date]) -> pd.DataFrame:
    """Fetch ALL BTC option trades for one UTC day, keep last trade per
    instrument, filter to target expiries locally."""
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

    # Filter to target expiries, extract fields
    expiry_set = {e.isoformat() for e in expiry_dates}
    rows = []
    for _, t in df.iterrows():
        inst_expiry = parse_expiry_from_instrument(t["instrument_name"])
        if inst_expiry not in expiry_set or t.get("iv") is None:
            continue
        rows.append(build_row(day, t, start_ms))  # same schema as today

    return pd.DataFrame(rows)
```

2. **Main loop**: One bulk call per day covering all target expiries at once.

```python
for delta in range(1, LOOKBACK_DAYS + 1):
    day = today - dt.timedelta(days=delta)
    if day_already_in_csv(day):          # checkpoint: skip fetched days
        continue
    targets = [month_end_expiry(day)] + quarterly_expiries(day)
    df = collect_surface_bulk(day, targets)
    if not df.empty:
        append_csv(df)
```

3. **Runtime**: ~1,095 days × ~3 paginated calls/day = ~3,300 API calls ×
   0.2s ≈ **~11 minutes** (vs 15 hours with per-instrument approach). The
   existing `append_csv` pattern supports checkpoint/resume — on restart,
   days already in the CSV are skipped.

4. **Output format**: Same CSV schema (`date, expiry, instrument, strike,
   option_type, ttm_days, iv, price`). Quarterly rows have TTM values in
   the 60–400 day range. No schema change.

## Stage 2: Per-Tenor SVI Calibration (iv_surface_svi.py)

### Current Behaviour

One SVI fit per day using all options pooled together. This works for
short-dated data where all options share similar TTMs (15–41 days). With
mixed tenors (30-day and 365-day), pooling is wrong: the total variance
`w = iv^2 * T` at the same moneyness differs by tenor, and one SVI curve
cannot fit both.

**Existing code to reuse**: `TTM_GRID` in `iv_surface_svi.py` already
includes `[90, 180, 270, 365]` (line 25), so the surface generation loop
already iterates over long-dated TTMs. The problem is that the SVI params
fed into those iterations come from a single calibration on short-dated
data. After per-tenor calibration, each bucket's own params are used for
its TTM range — the grid itself doesn't change.

### Changes

1. **Tenor bucketing**: Assign each option to a tenor bucket before
   calibration.

   | Bucket | TTM range (days) | Typical source |
   |--------|------------------|----------------|
   | short  | 3–60             | Month-end contracts |
   | 90d    | 60–135           | ~3 month quarterly |
   | 180d   | 135–225          | ~6 month quarterly |
   | 270d   | 225–315          | ~9 month quarterly |
   | 365d   | 315–400          | ~12 month quarterly |

2. **Per-tenor calibration**: For each `(date, tenor_bucket)` group, run
   `calibrate_svi(k, t, iv)` independently. This gives separate SVI
   parameters `(a, b, rho, m, sigma)` per tenor bucket per day. Within
   each bucket the TTM variation is small (e.g. all ~85–95 days for the
   90d bucket), so pooling within a bucket is acceptable.

3. **Sparse data fallback**: Quarterly options are less liquid than monthlies.
   On days where a tenor bucket has fewer than `min_quotes` (default 6)
   observations, skip calibration for that bucket and carry forward the most
   recent successful calibration. This is implemented via forward-fill on the
   params DataFrame, grouped by `tenor_bucket`.

   **Staleness cap**: Add a `max_ff_gap` parameter (default 21 calendar
   days). If a tenor bucket's most recent successful calibration is older
   than `max_ff_gap`, drop the row instead of forward-filling. This
   prevents silently using month-old params for illiquid tenors. Rows
   dropped this way produce NaN in the surface — the simulator's
   nearest-date fallback in `lookup_iv` handles this gracefully by
   selecting the next-nearest calibrated date.

4. **Params CSV**: Gains a `tenor_bucket` column. Each row is now
   `(date, tenor_bucket, a, b, rho, m, sigma, error, quotes)`. The
   existing "short" bucket rows remain identical to the current output.

5. **Surface generation**: When building the synthetic IV grid, iterate over
   each `(date, tenor_bucket)` row, and generate moneyness grid points at
   that bucket's representative TTM only (90, 180, 270, or 365 days). The
   "short" bucket uses the existing 15–60 day grid. Each long-tenor entry
   now comes from its own dedicated SVI fit instead of being extrapolated
   from short-dated params.

## Stage 3: Consumption (Rolldown Simulator)

### Data-side fix (no structural changes)

The consumption code's architecture is correct — the tenor mismatch fix
is entirely in the data it receives.

- `build_iv_tables(surface, price, [90, 180, 270, 365])` calls
  `build_weekly_iv_table(surface, price, tenor_days=T)` for each tenor.
  Currently the surface CSV only contains TTMs 15–60 (the long-dated
  entries from `TTM_GRID` were never populated because the SVI was only
  calibrated on short-dated data). So `build_iv_tables` maps 365 → 60
  (nearest available). With the new surface, real entries exist at each
  tenor: 365 → 365.

- `lookup_iv(surface, date, ttm_days, moneyness)` snaps to the nearest
  available TTM. With the new surface, querying TTM=365 returns IV from a
  dedicated 365-day SVI calibration rather than a 60-day extrapolation.

- `lookup_iv_weekly(iv_tables[tenor_days], rv, mny)` works identically,
  just with correctly-tenored data in the tables.

- The `simulate_single_loan` cutoff_date/iv_tables architecture is unchanged.

### Simulator bug fixes (code changes required)

Two bugs in the simulator code itself amplify the data-side tenor
mismatch. These must be fixed regardless of the surface quality.

#### Bug A: RV annualization mismatch (`rolldown_utils.py:95`)

`compute_rv_from_prices` annualizes a 7-day rolling std with
`np.sqrt(365)` (= 19.1), but `build_weekly_iv_table` (which builds the
lookup tables it queries against) uses `math.sqrt(365 / 7)` (= 7.2).
Same window, different annualization — the query RV is **2.65× inflated**,
so `lookup_iv_weekly` matches against crash-regime rows and returns
extreme IV values.

**Fix**: Change `rolldown_utils.py` line 95 from:
```python
return float(log_ret.std() * np.sqrt(365))
```
to:
```python
return float(log_ret.std() * np.sqrt(365 / window_days))
```

This makes the query RV use the same annualization as the table keys.

#### Bug B: Held PUT uses wrong tenor for IV lookup (`bitmor_rolldown_mc.py:113`)

When `use_rv=True`, the held PUT's IV is looked up from
`iv_tables[tenor_days]` where `tenor_days` is the **replacement** PUT's
tenor bucket, not the held PUT's actual remaining TTM. At month 10, the
replacement tenor is 90 days, but the held PUT may only have 61 days
left. The IV table and the BS pricing (`held_days_left / 365`) use
inconsistent tenors.

**Fix**: Compute a separate tenor bucket for the held PUT based on its
actual remaining days, and look up IV from that bucket.

In `bitmor_rolldown_mc.py`, change lines 111-114 from:
```python
if use_rv:
    rv = compute_rv_from_prices(daily_prices, current_date)
    iv_held = lookup_iv_weekly(iv_tables[tenor_days], rv, K_held / st)
    iv_repl = lookup_iv_weekly(iv_tables[tenor_days], rv, dt / st)
```
to:
```python
if use_rv:
    rv = compute_rv_from_prices(daily_prices, current_date)
    held_days_left_approx = max((held_expiry_date - current_date).days, 1)
    held_tenor_days = map_tenor_bucket_days(held_days_left_approx, list(iv_tables.keys()))
    iv_held = lookup_iv_weekly(iv_tables[held_tenor_days], rv, K_held / st)
    iv_repl = lookup_iv_weekly(iv_tables[tenor_days], rv, dt / st)
```

Where `map_tenor_bucket_days` maps a day count to the nearest available
IV table key (smallest bucket >= days, fallback to longest). Add to
`rolldown_utils.py`:
```python
def map_tenor_bucket_days(days: int, available_tenors_days: list[int]) -> int:
    """Map a day count to the nearest available IV table tenor (in days)."""
    for t in sorted(available_tenors_days):
        if t >= days:
            return t
    return max(available_tenors_days)
```

The non-RV path (line 116) has the same issue — `lookup_iv` snaps to the
nearest TTM in the surface, which is close enough given the dense TTM
grid. But for consistency, the same held-tenor logic should apply:
```python
else:
    iv_held = lookup_iv(surface, current_date, held_days_left_approx, K_held / st)
    iv_repl = lookup_iv(surface, current_date, tenor_days, dt / st)
```

(This requires moving `held_days_left` computation above the if/else
block, which is a trivial reorder.)

### IV source consistency after fix

The bigger win beyond consistency is **accuracy**: the 365-day SVI params
now reflect actual 365-day smile dynamics (skew, curvature, level) from
real long-dated trades, not a short-dated model extrapolated to a horizon
it was never calibrated on.

With correctly-tenored data, the two IV sources converge:

| Lookup method | Data source | When used |
|---------------|-------------|-----------|
| `lookup_iv` (surface) | SVI-fitted IV at TTM=365, nearest date | Month 0 + real months |
| `lookup_iv_weekly` (RV table) | SVI-fitted IV at TTM=365, matched by RV | Simulated months |

Both draw from the same underlying 365-day SVI calibrations. The only
difference is which historical date is selected: chronologically nearest
(surface) vs RV-nearest (table). Any IV difference between month 0 and
month 1 reflects genuine vol regime dynamics, not a methodology artefact.

## What This Fixes

| Issue | Before | After |
|-------|--------|-------|
| Tenor mismatch (data) | 365→60 day mapping | Exact 365→365 match |
| IV levels | 60-day smile applied to 365-day pricing | Real 365-day smile |
| RV-table quality | Built from wrong tenor data | Built from correct tenor data |
| RV annualization (Bug A) | Query RV 2.65× inflated vs table keys | Matched annualization (`sqrt(365/7)`) |
| Held PUT tenor (Bug B) | IV looked up at replacement tenor | IV looked up at held PUT's actual remaining TTM |
| Phantom profits | Large (3 compounding sources) | Small (only genuine vol regime changes) |
| Savings > 100% of premium | Yes (artefact) | No (unless genuinely earned) |

## What This Doesn't Change

- The SVI model type (raw SVI, same L-BFGS-B optimizer)
- The RV-based IV lookup mechanism (`lookup_iv_weekly`)
- The `simulate_single_loan` cutoff_date/iv_tables architecture (Bug B
  is a fix within the existing architecture, not a redesign)
- The three-tier simulation structure (Tier 1/2/3)
- The net_savings calculation (roll profits only, terminal delta separate)

## Data Availability Risk

Deribit quarterly options have lower liquidity than monthlies, especially
for deep OTM strikes. Expected issues:

- **Fewer quotes per day**: Some (date, tenor_bucket) pairs will have
  < 6 quotes. The forward-fill fallback handles this.
- **Missing tenors**: The 270d and 365d buckets will have the sparsest data.
  In the worst case, these buckets carry forward params for extended periods.
- **Strike coverage**: Long-dated options tend to cluster near ATM. The SVI
  fit may be less reliable in the wings (deep OTM puts at moneyness < 0.5).

These are acceptable for the rolldown simulator's use case: we price PUTs
at moneyness 0.5–0.8 (LTV range), which is near the well-observed region.

## File Changes Summary

| File | Change |
|------|--------|
| `btc_iv.py` | Replace per-instrument fetch with bulk `get_last_trades_by_currency_and_time`; add quarterly expiries to main loop (helper already exists); add checkpoint/resume |
| `iv_surface_svi.py` | Add tenor bucketing, per-bucket SVI calibration, forward-fill with staleness cap; surface generation uses per-bucket params (TTM_GRID already includes long tenors) |
| `rolldown_utils.py` | Fix RV annualization in `compute_rv_from_prices` (`sqrt(365)` → `sqrt(365/window_days)`); add `map_tenor_bucket_days` helper |
| `bitmor_rolldown_mc.py` | Use held PUT's actual remaining TTM for IV lookup instead of replacement tenor; reorder `held_days_left` computation above if/else block |

## Validation

After the pipeline runs, verify the fix before trusting simulation results:

1. **Surface sanity check**: Compare 365-day IV at a few (date, moneyness)
   points between old surface (extrapolated from short-dated SVI) and new
   surface (per-tenor calibrated). Old values should be unrealistically low
   (~15–20% for BTC); new values should be in the 40–70% range typical of
   real long-dated BTC options.

2. **Tenor coverage**: Check that the new surface CSV has entries at
   TTM=90/180/270/365. Currently it only has TTMs 15–60.
   ```bash
   cut -d',' -f2 btc_iv_surface_svi.csv | sort -n | uniq
   ```

3. **SVI fit quality**: Inspect per-tenor fit errors in `btc_svi_params.csv`.
   Flag tenor buckets where mean error is >2× the short bucket's error, or
   where >50% of rows are forward-filled (indicates sparse data).

4. **Simulator bug fixes**: Verify before running the full pipeline:
   - `compute_rv_from_prices` uses `sqrt(365/7)` (should match
     `build_weekly_iv_table`'s annualization)
   - Held PUT IV lookup uses `held_tenor_days` (not `tenor_days`)
   - Unit test: for a fixed daily price series, `compute_rv_from_prices`
     output should fall within the range of `real_vol` values in the IV
     table (i.e. not 2.65× above the max)

5. **Simulation regression**: Run Tier 2/3 and confirm:
   - `savings_pct` distributions no longer exceed 100% of premium
   - Tier 1 results are directionally similar to before (same data, same
     methodology — only the long-tenor surface quality changes)
   - Tier 2/3 savings are smaller and more realistic than pre-fix runs

## Execution

1. **Fix simulator bugs first** (can be done immediately, no data dependency):
   - Fix `rolldown_utils.py:95` — RV annualization (Bug A)
   - Fix `bitmor_rolldown_mc.py:111-117` — held PUT tenor lookup (Bug B)
   - Add `map_tenor_bucket_days` to `rolldown_utils.py`
   - Run simulation to verify savings drop (will still use 60-day tenor
     data, but at least the RV and tenor-bucket bugs are gone)

2. Run `python btc_iv.py` — fetches 3 years of data including quarterly
   contracts (~11 minutes with bulk API endpoint)
3. Run `python iv_surface_svi.py` — recalibrates with per-tenor SVI (minutes)
4. Run `python bitmor_rolldown_mc.py` — simulation uses correct IV data
   from correct tenors
5. Run validation checks above
