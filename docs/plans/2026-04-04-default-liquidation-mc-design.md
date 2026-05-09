# Default & Liquidation Monte Carlo — Design Document

**Date**: 2026-04-04
**Status**: Approved

## Purpose

Simulate the probability of borrower default on Bitmor BTC-backed loans and,
for each default event, determine whether the protocol's PUT option hedge
(rolled monthly via the rolldown strategy) plus BTC collateral is sufficient
to make lenders whole.

The core question: **given a default, does `BTC_value + PUT_mark_to_market`
cover `outstanding_debt + liquidator_fee`?**

## Decisions Made

| Decision | Choice | Rationale |
|---|---|---|
| Default model | Probabilistic (rational + exogenous) | Rational-only misses liquidity-driven defaults; pure random misses economic incentives |
| PUT valuation at default | Mark-to-market (Black-Scholes) | Protocol sells the option, doesn't exercise early; captures time value |
| Interest rate | Fixed 10% APR accrual | Pool utilization dynamics are out of scope; payment sized conservatively at 15% |
| Baseline config | 30% deposit, 12-month term | Matches rolldown model calibration; single config first, grid later |
| PUT strike | `snap_to_strike(ceil(spot × 0.70 × 1.03), spot)` rounded up | Realistic Deribit-listed strikes; 3% buffer above debt for collateralisation |
| Price paths | GBM or Merton jump-diffusion, with regime matching | GBM baseline + JD stress test; conditional IV responds to path dynamics |
| Exogenous default | Crash-correlated (scales with negative returns) | Flat rate misses default clustering in crashes; beta parameter links distress to price drops |

## Loan Origination (t=0)

- `spot_0` = BTC price at simulation start
- `deposit = 0.30 * spot_0`
- `loan_amount = 0.70 * spot_0` (principal in USD)
- `btc_bought = (loan_amount + deposit) / spot_0 = 1.0 BTC` (normalized)
- `put_strike = snap_to_strike(ceil(spot_0 * 0.70 * 1.03), spot_0)` — 3% buffer above debt, snapped up
- `put_qty = 1.0 BTC`
- Monthly payment `A` = annuity formula at 15% APR (conservative sizing), 12 months
- Debt accrues at 10% APR actual rate

### Loan state tracked each month

- `debt_outstanding` — principal + accrued interest - payments made
- `allocated_btc` — starts at 1.0, reduced by any micro-liquidation sales
- `put_K` — current held PUT strike (updated on rolls)
- `put_expiry_remaining` — days left on current PUT
- `cumulative_premiums_paid` — total insurance cost
- `months_paid` — payments completed

## Monthly Simulation Loop (months 1-12)

### Step 1 — Price evolution
Daily prices via GBM (baseline) or Merton jump-diffusion (stress). 30 days per month. `spot_m` = end-of-month price.

**Jump-diffusion model** (when `USE_JUMP_DIFFUSION = True`):
```
dS/S = (μ − λk) dt + σ dW + J dN
```
- `N ~ Poisson(λ dt)` — number of jumps per day (`λ = 0.10` → ~1.2 jumps/year)
- `J ~ exp(μ_J + σ_J Z) − 1` — log-normal jump size (`μ_J = -0.15`, `σ_J = 0.10`)
- `k = exp(μ_J + σ_J²/2) − 1` — drift compensation so E[S] is unbiased

### Step 2 — Debt accrual
`debt_m = debt_{m-1} * (1 + 0.10/12)` — 10% APR, monthly compounding.

### Step 3 — PUT rolldown
- Regime matching: find historical surface date whose trailing 7-day return best matches the simulated path's trailing return
- Look up IV from SVI surface at `(matched_date, remaining_ttm, moneyness = put_K / spot_m)`
- Price held PUT via Black-Scholes at mark-to-market
- Price replacement PUT at new strike `snap_to_strike(ceil(debt_m * 1.03), spot_m)` — strike = 103% of debt, snapped up
- If roll is profitable (held PUT value - replacement cost >= threshold): execute roll, update `put_K`, record roll profit, deduct slippage via `apply_slippage()`

### Step 4 — Default check (two independent channels)

**(a) Exogenous default**: Crash-correlated monthly probability. Base rate `p_exog` (0.5%/month) scales up during price drops:
```
p_adjusted = p_exog * (1 + crash_beta * max(0, -monthly_return))
```
With `crash_beta=3.0` and a -20% monthly return: `0.005 * (1 + 3*0.20) = 0.008` (60% higher). Bernoulli draw. Borrower can't pay regardless of economics — but distress clusters with crashes.

**(b) Rational default**: Borrower compares:
- `continuing_cost = (12 - m) * A` — remaining payments on current loan
- `restart_cost = new_deposit + new_total_payments` — 30% deposit at current spot + annuity over 12 months for new loan at current debt level
- Borrower forfeits existing deposit + all payments made so far
- `savings = continuing_cost - restart_cost`
- If `savings > 0`: probability = `sigmoid(savings / A)` — scales smoothly from ~0% to ~100%

If either channel triggers, the loan enters the liquidation waterfall.

## Liquidation Waterfall (on default)

### Assets
1. `btc_value = allocated_btc * spot_m`
2. `put_mtm = BS(spot_m, put_K, remaining_ttm, IV) - apply_slippage()`

### Liabilities
1. `debt_m` — outstanding debt
2. `liquidator_fee = 0.03 * debt_m`

### Coverage ratio
```
coverage = (btc_value + put_mtm_after_slippage) / (debt_m + liquidator_fee)
```

### Waterfall ordering (per Bitmor litepaper)
1. Sell BTC -> proceeds repay debt
2. If BTC < debt + fee -> sell PUT to cover shortfall
3. If total proceeds >= debt + fee -> lender whole, liquidator paid, surplus to **protocol**
4. If total proceeds < debt + fee -> **shortfall**, lender takes loss

### Per-path output record
```
path_id, default_month, default_type (rational/exogenous),
spot_at_default, debt_at_default, btc_value, put_strike, put_mtm,
put_mtm_after_slippage, total_proceeds, total_liabilities,
coverage_ratio, shortfall_usd, surplus_to_protocol
```

## Reporting & Outputs

### Aggregate metrics
1. **Default rate** — % paths defaulted (total, rational-only, exogenous-only)
2. **Coverage ratio distribution** — histogram with median, 5th/95th percentiles
3. **Shortfall probability** — % of defaults where coverage < 1.0
4. **Shortfall severity** — mean & worst-case shortfall (USD and % of principal)
5. **Time-to-default distribution** — defaults by month
6. **Surplus to protocol** — mean & distribution when coverage > 1.0

### Output files
- `results/path_details.csv` — one row per defaulted path
- `results/summary.csv` — single row with aggregate metrics
- `results/coverage_histogram.png` — coverage ratio distribution
- `results/default_timing.png` — bar chart of defaults by month
- Console summary

## File Structure

```
default-and-liquidation-mc/
├── config.py                  # Loan params, MC params, paths to shared data
├── default_model.py           # Rational + crash-correlated exogenous default
├── price_paths.py             # Merton jump-diffusion path generator
├── liquidation_waterfall.py   # BTC sale + PUT MTM -> coverage ratio
├── simulator.py               # Main MC loop
├── report.py                  # Aggregate metrics, CSVs, plots
├── main.py                    # CLI entry point (--jd flag for jump-diffusion)
├── results/
└── tests/
    ├── test_default_model.py
    ├── test_price_paths.py
    └── test_waterfall.py
```

## Data Dependencies (read in place, no duplication)

**From `../Monte carlo for insurance cost/`:**
- `btc_iv_surface_svi.csv` — SVI surface for IV lookups
- `BTCUSDT_1h.csv` — hourly prices for GBM calibration

**Code imports from `../Monte carlo for insurance cost/`:**
- `rolldown_utils.py`: `lookup_iv()`, `snap_to_strike()`, `apply_slippage()`, `RegimeIndex`, `generate_gbm_path()`, `calibrate_hist_mu_sigma()`
- `liquidation_utils.py`: `bs_price()`, `load_surface()`, `load_price()`

## Configuration Defaults

```python
DEPOSIT_PCT       = 30
LOAN_TERM_MONTHS  = 12
ACCRUAL_APR       = 0.10
SIZING_APR        = 0.15       # conservative payment sizing
LIQ_BUFFER        = 0.03       # 3% liquidator fee
P_EXOG_MONTHLY    = 0.005      # 0.5% exogenous default per month
EXOG_CRASH_BETA   = 3.0        # exogenous prob scales with negative returns
USE_JUMP_DIFFUSION = False     # True → Merton JD; False → plain GBM
JD_JUMP_INTENSITY = 0.10       # λ: ~1.2 jumps / year
JD_JUMP_MEAN      = -0.15      # μ_J: mean log-jump (negative = crashes)
JD_JUMP_STD       = 0.10       # σ_J: jump size volatility
MC_PATHS          = 10_000
GBM_SEED          = 42
```
