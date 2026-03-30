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
1. **Tenor mismatch**: `build_iv_tables` maps 365 → 60 (nearest available),
   but 60-day and 365-day IV smiles are structurally different.
2. **IV source switch**: month 0 uses direct surface lookup, month 1+ uses
   RV-based table lookup. With mismatched tenors, the two sources return
   very different IV levels for the same option.

Tier 1 (pure historical) is unaffected because it uses the same surface
lookup for both initial and monthly pricing.

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
the target expiry. The main loop calls this once per day, collecting trades
for the single month-end contract.

### Changes

1. **Parameterise `collect_surface`**: Accept a target expiry date instead of
   computing it internally. Rename to `collect_surface_for_expiry(day,
   instruments, expiry_date)`.

2. **Main loop extension**: For each day, call the collection function once
   for month-end, then once per quarterly expiry returned by
   `quarterly_expiries(day)`.

```python
for delta in range(1, LOOKBACK_DAYS + 1):
    day = today - dt.timedelta(days=delta)

    # Existing: month-end contract
    me_expiry = month_end_expiry(day)
    df = collect_surface_for_expiry(day, instruments, me_expiry)
    if not df.empty:
        append_csv(df)

    # New: quarterly expiry contracts
    for q_exp in quarterly_expiries(day):
        q_df = collect_surface_for_expiry(day, instruments, q_exp)
        if not q_df.empty:
            append_csv(q_df)
```

3. **Rate limiting**: Quarterly expiries add up to 4 extra API call batches
   per day. At 0.2s sleep per call, this is manageable but increases total
   runtime. For 1,095 days × ~5 expiries × ~50 instruments ≈ longer runtime
   (estimate: 4–8 hours total).

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
   parameters `(a, b, rho, m, sigma)` per tenor bucket per day.

3. **Sparse data fallback**: Quarterly options are less liquid than monthlies.
   On days where a tenor bucket has fewer than `min_quotes` (default 6)
   observations, skip calibration for that bucket and carry forward the most
   recent successful calibration. This is implemented via forward-fill on the
   params DataFrame, grouped by `tenor_bucket`.

4. **Params CSV**: Gains a `tenor_bucket` column. Each row is now
   `(date, tenor_bucket, a, b, rho, m, sigma, error, quotes)`. The
   existing "short" bucket rows remain identical to the current output.

5. **Surface generation**: When building the synthetic IV grid, iterate over
   each `(date, tenor_bucket)` row, and generate moneyness grid points at
   that bucket's representative TTM only (90, 180, 270, or 365 days). The
   "short" bucket generates the existing 15–60 day grid. Result: the surface
   CSV has real entries at TTM 90/180/270/365, each from their own dedicated
   SVI fit.

## Stage 3: Consumption (Rolldown Simulator)

### No structural changes needed

The existing consumption code already handles per-tenor IV correctly:

- `build_iv_tables(surface, price, [90, 180, 270, 365])` calls
  `build_weekly_iv_table(surface, price, tenor_days=T)` for each tenor.
  Currently this maps 365 → 60 (nearest available). With the new surface,
  it finds exact matches: 365 → 365.

- `lookup_iv(surface, date, ttm_days, moneyness)` snaps to the nearest
  available TTM. With the new surface, querying TTM=365 returns actual
  365-day SVI-fitted IV instead of extrapolated 60-day IV.

- `lookup_iv_weekly(iv_tables[tenor_days], rv, mny)` works identically,
  just with correctly-tenored data in the tables.

- The `simulate_single_loan` cutoff_date/iv_tables architecture is unchanged.

### IV source consistency after fix

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
| Tenor mismatch | 365→60 day mapping | Exact 365→365 match |
| IV levels | 60-day smile applied to 365-day pricing | Real 365-day smile |
| RV-table quality | Built from wrong tenor data | Built from correct tenor data |
| Phantom profits | Large (IV source + tenor mismatch) | Small (only genuine vol regime changes) |
| Savings > 100% of premium | Yes (artefact) | No (unless genuinely earned) |

## What This Doesn't Change

- The SVI model type (raw SVI, same L-BFGS-B optimizer)
- The RV-based IV lookup mechanism (`lookup_iv_weekly`)
- The `simulate_single_loan` cutoff_date/iv_tables architecture
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
| `btc_iv.py` | Parameterise `collect_surface`, add quarterly collection to main loop |
| `iv_surface_svi.py` | Add tenor bucketing, per-bucket SVI calibration, forward-fill fallback |
| `rolldown_utils.py` | No changes (build_iv_tables already handles exact tenor matches) |
| `bitmor_rolldown_mc.py` | No changes |

## Execution

After code changes:
1. Run `python btc_iv.py` — fetches 3 years of quarterly data (4–8 hours)
2. Run `python iv_surface_svi.py` — recalibrates with per-tenor SVI (minutes)
3. Run `python bitmor_rolldown_mc.py` — simulation uses correct IV data
