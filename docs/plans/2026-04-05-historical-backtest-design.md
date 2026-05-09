# Historical Backtest — Design Document

**Date**: 2026-04-05
**Status**: Approved

## Purpose

Answer a single question with zero simulation: **has there ever been a historical moment where `BTC_collateral + PUT_mark_to_market < outstanding_debt + liquidator_fee`?**

For every loan that could have been originated from April 2021 through March 2025, replay the actual BTC price path and actual IV surface data day-by-day. No Monte Carlo, no randomness — pure historical replay.

## Decisions Made

| Decision | Choice | Rationale |
|---|---|---|
| Price source | Actual historical BTC hourly → daily | Real prices, no simulation |
| IV source | Actual SVI surface for that exact date | We have daily surface data; no regime matching needed |
| Coverage check frequency | Daily (every day of loan life) | User requirement; catches intra-month stress |
| PUT rolldown frequency | Monthly (30-day boundaries) | Matches protocol mechanics |
| Loan origination frequency | Every calendar day in backtest window | ~1,460 loans; tractable, no sampling needed |
| Visualization | Interactive Plotly HTML, Bitmor design language | Consistent with existing dashboard |

## Data Availability

- **Price data**: Aug 2017 – Mar 2026 (hourly, `BTCUSDT_1h.csv`)
- **IV surface**: Apr 2021 – Mar 2026 (daily, `btc_iv_surface_svi.csv`)
- **Effective backtest window**: Apr 2021 – Mar 2025 (loans need 12 months forward prices)
- **Total loans**: ~1,460 (one per day)
- **Total daily checks**: ~525,000

## Loan Mechanics (per origination date)

Same parameters as the MC simulation:

- `spot_0 = price[origination_date]`
- `deposit = 0.30 * spot_0`
- `loan_amount = 0.70 * spot_0`
- `btc_held = 1.0` (normalized)
- `put_K = snap_to_strike(ceil(spot_0 * 0.70 * 1.03), spot_0)`
- Monthly payment `A` = annuity at 15% APR, 12 months
- Debt accrues at 10% APR daily: `debt *= (1 + 0.10/365)`
- Payment deducted at 30-day boundaries (day 30, 60, 90, ...)

## Daily Coverage Check

For each day `t` (0–359) of each loan:

```
btc_value = 1.0 * spot[origination_date + t]
remaining_ttm = put_expiry_days - t
moneyness = put_K / spot_now
iv = lookup_iv(surface, calendar_date, remaining_ttm, moneyness)
put_mtm = BS(spot_now, put_K, remaining_ttm/365, 0.0, iv, call=False)
put_mtm_net = put_mtm - slippage

coverage = (btc_value + put_mtm_net) / (debt + 0.03 * debt)
```

## PUT Rolldown (monthly boundaries)

At days 30, 60, 90, ..., 330:
1. Value held PUT using actual IV surface at that date
2. Price replacement PUT at `snap_to_strike(ceil(debt * 1.03), spot)` with new tenor
3. Roll if profitable (held value - replacement - slippage > 0)
4. Update `put_K` and `put_expiry_days` if rolled

## IV Lookup Strategy

Direct lookup from actual SVI surface — no regime matching:
1. For date `d + t`, compute `(remaining_ttm, moneyness)`
2. `lookup_iv(surface, date, ttm_days, moneyness)` — nearest-neighbor on tenor and moneyness
3. Fallback to nearest available surface date if exact date missing (weekends/holidays)

## Output

### CSVs
- `results/backtest/daily_coverage.csv` — full matrix (~525k rows): origination_date, day_in_loan, calendar_date, spot_0, spot_now, debt, put_K, put_ttm_days, put_iv, put_mtm, put_mtm_after_slippage, btc_value, total_proceeds, total_liabilities, coverage_ratio
- `results/backtest/worst_by_loan.csv` — one row per loan: origination_date, min_coverage, min_coverage_day, spot_0, spot_at_worst, debt_at_worst, max_drawdown_pct
- `results/backtest/backtest_summary.csv` — single-row aggregate stats

### Interactive HTML Report
Single self-contained `results/backtest/backtest_report.html` using the Bitmor design language (dark theme, `#030916` bg, `#F25E13` accent, Bricolage Grotesque + IBM Plex Mono, Plotly).

**Chart 1: Min-Coverage Time Series + BTC Price Overlay**
- X-axis: origination date
- Y-axis (left): minimum coverage ratio for that loan
- Y-axis (right): BTC price at origination
- Horizontal line at coverage = 1.0
- Shows which vintage loans were most stressed

**Chart 2: Coverage vs Spot Drawdown Scatter**
- X-axis: % change from origination `(spot_now - spot_0) / spot_0`
- Y-axis: coverage ratio
- Every daily observation plotted
- Horizontal line at 1.0
- Shows structural relationship between price drops and coverage

**Chart 3: Worst-10 Loan Lifecycle Curves**
- X-axis: day in loan (0–359)
- Y-axis: coverage ratio
- One line per loan (top 10 worst by min coverage)
- Shows how stress evolved over the loan life

**Table: Coverage During Known Stress Events**
- One row per stress event: LUNA/UST collapse (May 2022), 3AC/Celsius contagion (Jun 2022), FTX collapse (Nov 2022)
- Columns: event name, period, active loans count, min coverage, median coverage, breach days
- Shows at a glance whether the hedge held during the worst historical episodes

### Console Summary
- Total loans tested
- Any coverage breaches (coverage < 1.0)?
- Worst coverage ratio, which loan, which day
- Mean/median min-coverage across all loans
- Pass/fail verdict

## File Structure

```
default-and-liquidation-mc/
├── historical_backtest.py      # Core: loan replay + daily coverage engine
├── backtest_report.py          # HTML report, CSVs, console summary
├── run_backtest.py             # CLI entry point
├── results/backtest/           # Output directory
│   ├── daily_coverage.csv
│   ├── worst_by_loan.csv
│   ├── backtest_summary.csv
│   └── backtest_report.html
```

## Reused Code

From this project:
- `config.py` — loan params, paths
- `liquidation_waterfall.py` — `compute_waterfall()`
- `default_model.py` — `compute_annuity()`

From `../Monte carlo for insurance cost/`:
- `rolldown_utils.py`: `lookup_iv()`, `snap_to_strike()`, `apply_slippage()`
- `liquidation_utils.py`: `bs_price()`, `load_surface()`, `load_price()`
