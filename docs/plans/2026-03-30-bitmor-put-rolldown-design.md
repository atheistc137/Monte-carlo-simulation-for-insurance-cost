# Bitmor PUT Roll-Down Cost Reduction Simulator — Design

## Problem

In Bitmor, a BTC-collateralized USDC loan is hedged with a PUT option to eliminate
liquidation risk. As the borrower makes monthly amortized payments, the outstanding
debt shrinks, meaning the required hedge (PUT strike) also shrinks. This creates
opportunities to sell the existing PUT and buy a cheaper one at a lower strike,
pocketing the difference. We want to quantify the average cost reduction from this
rolling strategy via historical backtest, to give users a realistic savings estimate.

## Simulation Approach: Three-Tier Analysis

### Why Not Just Monte Carlo?

A pure MC from today's price with GBM assumes constant drift/vol and misses real
market regimes (2022 crash, 2023 grind, 2024 rally). For validating a strategy
and quoting realistic savings, historical backtesting is more credible and defensible.
However, a forward-looking MC from today's price is still useful for quoting
expected savings to a borrower starting a loan right now. We do all three.

### Tier 1: Pure Historical Backtest

- **Start dates:** Every day from 3 years ago to 1 year ago (~730 loans)
- **Data:** 100% actual BTC prices and actual IV surface at each monthly checkpoint
- **No simulation, no GBM, no assumptions**
- Answers: "what would have happened across different market regimes?"

### Tier 2: Recent Loans with Simulated Tails

- **Start dates:** Every day in the last 1 year (~365 loans)
- **Data:** Actual prices/IV up to today, then GBM forward for remaining months
- **MC paths:** 1000 GBM paths per start date for the simulated tail
- **IV during simulated months:** frozen at the last available IV surface
- **GBM calibration:** mu/sigma from trailing historical data
- Answers: "what can recent borrowers expect going forward?"

### Tier 3: Forward MC from Today's Price

- **Start date:** Today (current BTC spot price)
- **Data:** No historical price path — full 12-month GBM simulation
- **MC paths:** 1000 full paths (configurable via `--n_forward_paths`)
- **IV:** Frozen at the latest available IV surface
- **GBM calibration:** mu/sigma from all available historical data
- **Individual path results reported** (not just averages)
- Answers: "what should a borrower starting today expect?"

### Reporting

Each tier is reported independently — no weighted average across tiers.
Tiers have fundamentally different data quality (real vs simulated) and mixing
them into a single number would obscure that distinction.

### Start Date Frequency

Default is daily for Tiers 1 and 2. Configurable via `--start_freq`
(daily/weekly/monthly) for faster runs during development. Daily gives the
smoothest picture and captures every possible entry point. Adjacent loans overlap
heavily but that is expected and correct — it shows how the strategy performs for
every borrower.

## Loan & Hedge Mechanics

### Origination (month 0)
- Borrower holds 1 BTC at spot price S0 (the actual BTC price on the start date)
- Loan amount (USDC): D0 = LTV * S0
- PUT purchased: strike = D0, tenor = 12 months
- Initial PUT cost: BS(S0, D0, 1yr, r, IV) where IV is looked up from the actual
  IV surface at that date, for 365-day tenor and moneyness D0/S0

### Monthly Evaluation (months 1 through 11)
Each month t:
1. Get BTC spot (actual historical price, or GBM-simulated in Tier 2 tail)
2. Compute outstanding debt Dt from amortization schedule
3. Determine applicable tenor bucket for remaining loan life:
   - Remaining 10-12 months -> 12m (365-day) IV
   - Remaining 7-9 months -> 9m (270-day) IV
   - Remaining 4-6 months -> 6m (180-day) IV
   - Remaining 1-3 months -> 3m (90-day) IV
4. Price held PUT: BS(St, K_held, time_to_held_expiry, r, IV_applicable)
   - IV looked up from actual surface at that date (or frozen surface for simulated months)
   - Moneyness = K_held / St
5. Price replacement PUT: BS(St, Dt, replacement_tenor, r, IV_applicable)
   - Replacement tenor = smallest available tenor >= remaining loan life
   - Moneyness = Dt / St
   - Note: replacement tenor can slightly exceed remaining loan life due to
     discrete tenors (e.g. 11 months remaining → 12m put). This is a
     deliberate conservative bias — overpays for time value, making roll
     savings estimates worse than reality.
6. Roll profit = held_value - replacement_cost
7. If roll_profit >= $200: execute roll, update K_held and held_expiry

### Expiration (month 12)
- PUT expires: payoff = max(K_held - S_final, 0)
- Record terminal payoff for both static and rolling strategies

## IV Surface Lookup

### During Historical Months (actual data available)
Direct lookup from the SVI surface: given (date, ttm_days, moneyness) -> IV.
Find nearest date in surface, then nearest moneyness at the required tenor.

### During Simulated Months (Tier 2 tail, Tier 3)
Use the existing RV-based empirical lookup from `liquidation_utils.py`:
`lookup_iv_weekly(table, realized_vol, moneyness)`. This captures the
price-IV dependency: crash paths produce high realized vol → high IV,
calm paths → low IV.

**Realized vol on simulated paths:** Simulated tails use daily GBM steps
(matching `liquidation_insurance_mc.py`), with option evaluation at monthly
checkpoints only. A rolling 7-day window of daily simulated prices feeds
`realised_vol(last_7)` — the same function used by the existing simulator —
to compute the RV input for `lookup_iv_weekly`.

**Per-tenor IV tables:** Built once from historical data by calling
`build_weekly_iv_table(surface, price, tenor_days=T)` for each T in
[90, 180, 270, 365], stored in a dict keyed by tenor days:
`iv_tables = {90: tbl_90, 180: tbl_180, 270: tbl_270, 365: tbl_365}`.
At each monthly checkpoint the correct table is selected based on the
applicable tenor bucket from step 3.

A `cutoff_date` parameter in `simulate_single_loan` controls
when to switch from direct surface lookup (real months) to RV-based lookup
(simulated months):
- Tier 1: `cutoff_date=None` → all surface (pure historical)
- Tier 2: `cutoff_date=last_real_date` → surface for real months, RV for tail
- Tier 3: `cutoff_date=start_date` → RV for all months

## Comparison: Static vs Rolling

**Static strategy (baseline):**
- Buy 12m PUT at origination, hold to expiry
- Net cost = initial_premium - terminal_payoff

**Rolling strategy:**
- Same initial PUT
- Monthly roll evaluation, minimum $200 profit threshold
- Net cost = initial_premium - sum(roll_profits) - terminal_payoff

**Savings = static_cost - rolling_cost
        = sum(roll_profits) + (terminal_payoff_rolling - terminal_payoff_static)**

Terminal payoffs differ because the rolling strategy holds a lower final strike.
The second term is always ≤ 0 (rolling gives up downside protection). Roll profits
are not free money — they are the fair-value cost of reducing the hedge. In bull
markets the terminal penalty is zero (both PUTs expire worthless) so roll profits
are kept. In bear markets the penalty can exceed cumulative roll profits, making
rolling worse than static.

## Configurable Parameters

| Parameter | Default | Description |
|---|---|---|
| s0 | (from data) | Spot price at loan start (actual historical price) |
| ltv | 0.70 | Loan-to-value ratio |
| loan_tenor_months | 12 | Loan duration in months |
| loan_rate | 0.10 | Annual interest rate |
| payments_per_year | 12 | Payment frequency |
| available_tenors | [3, 6, 9, 12] | Available option tenors in months |
| min_roll_profit | 200 | Minimum USD profit to trigger a roll |
| n_mc_paths | 1000 | MC paths per start date (Tier 2 only) |
| n_forward_paths | 1000 | Full MC paths from today's price (Tier 3) |
| r | 0.0 | Risk-free rate for BS pricing |
| backtest_years | 3 | How far back to look for Tier 1 start dates |
| start_freq | daily | Loan start date frequency (daily/weekly/monthly) |
| seed | None | Random seed for reproducibility |

### Performance Note

Tier 2 with daily start dates: 365 starts × 1000 paths × ~365 daily GBM
steps ≈ 133M steps. Feasible but not instant (~minutes). Use
`--start_freq weekly` or `--start_freq monthly` during development for
faster iteration.

## IV Surface Data Requirements

The existing pipeline fetches short-dated (15-60 day) options. Must be extended:

1. **btc_iv.py**: Fetch options with ~90, ~180, ~270, ~365 day expiries from Deribit
   (quarterly expiries), in addition to existing month-end contracts.
2. **iv_surface_svi.py**: Extend TTM_GRID to include [90, 180, 270, 365] day tenors.
   SVI calibration covers the full maturity range.
3. **Surface CSV**: After re-running, `btc_iv_surface_svi.csv` will contain rows for
   all 4 quarterly tenors across the full 3-year date range.

## Output

```
=== Tier 1: Pure Historical (N loans, start dates YYYY-MM-DD to YYYY-MM-DD) ===
  Avg initial PUT premium        : $X
  Avg Σ roll profits             : $X
  Avg terminal payoff (static)   : $X
  Avg terminal payoff (rolling)  : $X
  Avg net savings                : $X (Y% of premium)
  Median net savings             : $X
  Range                          : $X to $X
  Avg rolls per loan             : N
  % loans where rolling helped   : Z%

  Per-loan breakdown:
    Start YYYY-MM-DD | Spot $X | Premium $X | Roll Profits $X | Terminal Δ $X | Net Savings $X (Y%) | Rolls: N

=== Tier 2: Recent + Simulated (M start dates x 1000 paths) ===
  (same stats as Tier 1, averaged across MC paths per start date)

  Per-start-date breakdown:
    Start YYYY-MM-DD | Spot $X | Premium $X | Avg Roll Profits $X | Avg Terminal Δ $X | Avg Net Savings $X (Y%) | Avg Rolls: N

=== Tier 3: Forward MC from Today (1000 paths, spot = $X) ===
  Initial PUT premium            : $X
  Avg Σ roll profits             : $X
  Avg terminal payoff (static)   : $X
  Avg terminal payoff (rolling)  : $X
  Avg net savings                : $X (Y% of premium)
  Median net savings             : $X
  Range                          : $X to $X
  Avg rolls per path             : N
  % paths where rolling helped   : Z%
  Percentiles (5/25/50/75/95)    : ...

  Individual path results (all 1000):
    Path # | Final Spot $X | Roll Profits $X | Terminal Δ $X | Net Savings $X (Y%) | Rolls: N
```

Results saved to CSV:
- `result/rolldown_tier1_YYYYMMDD.csv` — per-loan historical results
- `result/rolldown_tier2_YYYYMMDD.csv` — per-start-date recent results
- `result/rolldown_tier3_YYYYMMDD.csv` — individual forward MC path results

## File Structure

- `bitmor_rolldown_mc.py` — Main simulation script (CLI entry point)
- `rolldown_utils.py` — Core helpers (tenor mapping, surface lookup, roll logic)
- `btc_iv.py` — Extended to fetch quarterly expiry data
- `iv_surface_svi.py` — Extended TTM_GRID for quarterly tenors
- `liquidation_utils.py` — Existing utilities reused (bs_price, load_surface, etc.)

## Reuse from Existing Code

- `bs_price` from liquidation_utils.py (Black-Scholes pricing)
- `load_surface`, `load_price` (CSV loaders)
- `calibrate_hist_mu_sigma` (for Tier 2 GBM calibration)
- `build_amortisation_schedule` (amort schedule)
- `build_weekly_iv_table` (called per tenor to build iv_tables dict)
- `lookup_iv_weekly` (RV-based IV lookup for simulated months)
- `realised_vol` concept from `liquidation_insurance_mc.py` (7-day rolling window)
- `gbm_step` concept (daily steps for simulated tails, option eval at monthly checkpoints)
