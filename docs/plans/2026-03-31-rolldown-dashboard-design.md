# PUT Roll-Down Dashboard — Design

## Purpose

Single-file HTML visualization of the three-tier rolldown simulation results.
Audience: evaluators assessing whether the upfront PUT premium is substantially
recoverable via the rolling strategy. Tone: factual, evidence-based — present
the simulation methodology and results, let the data speak.

## Technology

- **Plotly.js** from CDN (only external dependency)
- Inline CSS, no framework
- Data embedded as JS string literals, parsed client-side with simple splitter
- Total data: ~2,100 rows across 3 CSVs (~250KB)

## Page Structure

```
Header: title + one-line description
┌──────────┬──────────┬──────────────────┐
│ [Tier 1] │ [Tier 2] │ [Tier 3]         │  ← tab toggle
│ Historic │ Recent   │ Forward Sim      │
├──────────┴──────────┴──────────────────┤
│ Tier description (2-3 sentences)       │
│ Summary stats card (horizontal row)    │
│ Chart 1 (primary)                      │
│ Chart 2 (Tier 3 only)                  │
├────────────────────────────────────────┤
│ <details> Methodology note </details>  │
└────────────────────────────────────────┘
```

## Tier Framing

### Tier 1 — Historical Backtest (Bull Market)

731 loans starting daily from March 2023 to March 2025. BTC rose from ~$28k
to ~$87k. Every data point uses actual historical prices and actual IV
surface — no simulation. Shows strategy performance across a sustained rally.

### Tier 2 — Recent Loans (Bear Market + Simulated Tails)

366 loans starting daily from March 2025 to March 2026. BTC declined from
~$87k to ~$66k. Loans not yet expired are extended with 1,000 simulated
price paths each, averaged per start date. Tests whether the strategy holds
when markets move against the borrower.

### Tier 3 — Forward Simulation (1,000 Paths)

1,000 independent Monte Carlo paths from today's spot ($66,280). Full
12-month GBM simulation. Each path is an individual result, not averaged.
Shows the full distribution of possible outcomes starting today.

## Charts

### Tier 1 & 2: Time-Series

- **X-axis:** `start_date`
- **Y-axis (primary):** `full_economic_delta / initial_premium * 100`
  — labelled "% of Premium Recovered"
- **Secondary axis:** entry `spot` price as a light line, to anchor
  bull/bear market context visually
- **Reference line:** horizontal dashed at 0% (breakeven)
- **Rendering:** scatter points (not connected line)
- **Hover tooltip:** start date, entry spot ($), initial premium ($),
  roll savings ($), terminal delta ($), full economic delta ($ and %)

### Tier 3 Chart A: Histogram

- **Data:** `full_economic_delta` (USD)
- **Bins:** ~$500 width
- **Percentile markers:** vertical dashed lines at P5, P25, P50, P75, P95
  with value labels
- **Color:** green for delta > 0, red for delta < 0

### Tier 3 Chart B: Scatter

- **X-axis:** `final_spot` (where BTC ended up after 12 months)
- **Y-axis:** `full_economic_delta` (USD)
- **Purpose:** reveals the relationship — crash paths incur terminal
  penalty that eats roll savings; flat/up paths keep savings

## Summary Stats Card

Horizontal row of key numbers, displayed per tier:

| Stat                        | Tier 1/2        | Tier 3          |
|-----------------------------|-----------------|-----------------|
| Loans / Paths               | count           | count           |
| Avg Initial Premium         | $               | $ (constant)    |
| Median Recovery             | % of premium    | % of premium    |
| Median full_economic_delta  | $               | $               |
| % Where Delta > 0           | %               | %               |
| Avg Rolls per Loan          | N               | N               |
| P5 / P95                    | —               | $ / $           |

## Styling

- System font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- `max-width: 1200px`, centered
- Dark text on white, subtle borders
- Active tab highlighted, inactive tabs muted
- Charts: Plotly default palette, gridlines subdued
- No chart junk: no 3D, no gradient fills, no decorative elements

## Methodology Note

Collapsible `<details>` at page bottom. Briefly explains:
- What the rolling strategy is (sell high-strike PUT, buy lower-strike)
- What full_economic_delta captures (roll savings + terminal payoff difference)
- How Tier 2 simulated tails work (GBM calibrated from historical data)
- How Tier 3 paths are generated (GBM from current spot, frozen IV surface)
- Loan parameters used (70% LTV, 12-month term, 10% rate, $200 min roll profit)

## Data Files

- `result/rolldown_tier1_daily_20260331.csv` — 731 rows
- `result/rolldown_tier2_daily_20260331.csv` — 366 rows
- `result/rolldown_tier3_1000paths_20260331.csv` — 1,000 rows

All share columns: `start_date, spot, initial_premium, roll_savings,
roll_savings_pct, terminal_payoff_static, terminal_payoff_rolling,
terminal_delta, full_economic_delta, num_rolls, final_spot, debt_at_expiry`
