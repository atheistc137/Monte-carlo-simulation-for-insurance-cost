# Bitmor Combined Dashboard — Design

**Date:** 2026-03-31
**File:** `bitmor-dashboard.html`
**Approach:** Component-oriented single HTML file (Approach B)

## Overview

Combine the Bitmor Math Explainer and Rolldown Dashboard into a single self-contained HTML file with 3 tabs: General Explainer, Backtest & Simulations, and Methodology. The math explainer's PUT roll-down section is rewired to use actual backtest/simulation data instead of randomized values.

## Architecture

Single HTML file with 4 namespaced JS modules:

- **DataStore** — Parses all 3 CSV tiers at load, exposes query methods (`getRandomPath()`, `getRandomPathFromTier(n)`, `getTierStats(n)`, `getTierRows(n)`)
- **Tab1Controller** — Loan explainer (Sections 1-3), owns Section 3 path rendering
- **Tab2Controller** — Backtest/simulation results with narratives and Plotly charts
- **Tab3Controller** — Methodology reference page with anchored sections
- **Nav** — Tab switching, cross-link deep-linking (`goTo(tab, anchor)`), scroll-to-anchor with highlight flash

Charting: Plotly.js only (no Chart.js). CSS: unified dark theme shared by both source files (same colors, fonts, variables already). Lazy rendering: each tab's `init()` runs on first activation only.

## Tab 1: General Explainer

### Section 1: Loan Configuration (carried over from math explainer)
- Interactive sliders: BTC Price, APR, BTC Amount, Down Payment %, Loan Term
- Metrics: BTC Value, Down Payment, Financed Amount, Monthly Payment, Total Interest, Total Cost
- Black-Scholes pricing card with sensitivity sliders (Conservative/Base/Optimistic)
- Deribit live integration with fallback to snapshot (kept as-is)

### Section 2: Repayment Schedule (carried over from math explainer)
- Full amortization table: Month, Payment, Principal, Interest, Balance, % Paid
- Sticky header, scrollable

### Disclaimer (between Section 2 and Section 3)
> "Sections 1-2 above are interactive and illustrative — configure any loan to see its amortization. Section 3 below uses actual backtest and simulation data with fixed parameters (70% LTV, 12-month term, 10% APR). The path shown is randomly selected from 2,000+ historical and simulated loan outcomes."

### Section 3: PUT Roll-Down Strategy (rewired to real data)

On page load, `DataStore.getRandomPath()` picks one row with equal probability across Tier 1/2/3 (picks tier first with 33/33/33, then random row within tier).

**Path info badge** at top, clickable → navigates to corresponding tier on Tab 2:
- Tier 1: "Full Historical Backtest — Loan started [date], BTC at $[spot]"
- Tier 2: "Historical Entry + Simulated Forward — Loan started [date], BTC at $[spot]"
- Tier 3: "Full Monte Carlo Simulation — Starting from today's BTC at $[spot]"

**Debt Balance vs PUT Strike chart** (Plotly):
- Orange line: debt balance declining over 12 months (computed from path's `spot` + fixed loan params)
- Green dashed line: PUT strike stepping down at roll points
- Roll points reconstructed from `num_rolls` at evenly-spaced intervals

**Cash Flow Timeline:**
- Month-by-month events: Buy PUT, Sell PUT, Buy replacement
- Color-coded (green inflows, red outflows), running total
- Derived from path's `initial_premium`, `roll_savings`, `num_rolls`

**Summary metrics card:**
- Initial Premium, Roll Savings, Recovery %, Final Spot, Terminal Payoff, Num Rolls (all from CSV)

**"Reshuffle" button** — picks new random path, re-renders Section 3.

## Tab 2: Backtest & Simulations

Three tier sections stacked vertically with narrative intros, stats, and charts.

### Tier 1: Historical Backtest
**Narrative:** 731 real loans, March 2023-2025, BTC rallied $28k→$87k. PUT never pays out, all value from roll savings. Average recovery ~X% (computed from data).

**Stats cards:** Avg Initial Premium, Avg Roll Savings, Avg Recovery %, Avg Effective Cost %, Avg Num Rolls

**Chart:** Plotly scatter/line — roll_savings_pct over start_date

**Links:** "IV surface" → Tab 3 `#iv-surface`, "roll threshold" → Tab 3 `#roll-mechanics`

### Tier 2: Historical Entry + Simulated Forward
**Narrative:** 366 loans, March 2025-2026, BTC declined $87k→$66k. Incomplete loans extended with 1,000 simulated paths, averaged per start date. Some paths show non-zero terminal payoff — hedge pays out.

**Stats cards:** Same metrics as Tier 1

**Chart:** Same format — roll_savings_pct over start_date

**Links:** "See a random example from this tier →" reshuffles Tab 1 to Tier 2 path

### Tier 3: Forward Simulation
**Narrative:** 1,000 independent Monte Carlo paths from today's spot (~$66,280). Individual outcomes, not averaged. Distribution spans $18k crashes to $300k+ rallies. ~1/3 paths show positive terminal payoff.

**Stats cards:** Same metrics plus Median Recovery %, % paths with terminal payoff > 0

**Charts (2):**
1. Scatter — roll_savings_pct across paths (x = final_spot, y = roll_savings_pct)
2. Histogram — full_economic_delta distribution

**Links:** "GBM calibration" → Tab 3 `#gbm-calibration`, "frozen IV" → Tab 3 `#assumptions`

## Tab 3: Methodology

Single scrollable reference page. Anchored sections for deep-linking from Tabs 1-2.

| Anchor | Title | Content |
|--------|-------|---------|
| `#strategy` | Strategy Overview | Roll-down mechanics, $200 threshold, monthly checkpoints |
| `#roll-mechanics` | Roll Decision Mechanics | Sell/buy logic, strike tied to amortization |
| `#premium-recovery` | Premium Recovery | How recovery % is calculated |
| `#option-pricing` | Option Pricing | BS model for European cash-settled BTC options, rfr = 0 |
| `#iv-surface` | IV Surface | SVI parameterization, 700+ days, 5 tenors, arbitrage-free |
| `#gbm-calibration` | GBM Calibration | Drift/vol from 3yr BTCUSDT hourly, daily resolution |
| `#simulation-tiers` | Simulation Tiers | Tier 1/2/3 definitions |
| `#loan-parameters` | Loan Parameters | LTV 70%, 12mo, 10% APR, tenor selection |
| `#assumptions` | Key Assumptions | Frozen IV, no transaction costs, monthly checkpoints, constant GBM |
| `#data-sources` | Data Sources | Binance BTCUSDT, Deribit historical options |

Content is verbatim from rolldown dashboard methodology with minor cleanup.

**Reverse links (organic):**
- `#simulation-tiers` → links to each tier on Tab 2
- `#strategy` → "See a live example →" to Tab 1 Section 3

## Cross-Linking

All links call `Nav.goTo(tabNumber, anchorId)`:
1. Switches tab (triggers lazy init if first visit)
2. Scrolls to anchor
3. Brief orange border flash highlight (1s fade)

URL hash updates on tab switch (`#explainer`, `#backtests`, `#methodology`) for browser back button.

Special: Tab 2 "See a random example from this tier" calls `Tab1Controller.reshuffleFromTier(tierNumber)`.

## Data Reconciliation

Rolldown dashboard data is authoritative. Math explainer values used only for Sections 1-2.

| Item | Sections 1-2 | Section 3 + Tabs 2-3 |
|------|-------------|----------------------|
| Risk-free rate | 5% (BS calc) | 0% (simulation data) |
| Roll points | Fixed 1/3, 2/3 | Monthly checkpoints, $200 threshold |
| Sensitivity factors | 70%/85.5%/95% | Not applicable |
| Spot price | Slider-driven | From CSV |
| LTV/Term/APR | Configurable | Fixed: 70%, 12mo, 10% |
| Deribit data | Live + snapshot | Own IV surface |

## Technical Decisions

- **Charting:** Plotly.js only
- **Live API:** Kept for Section 1 (Deribit + Coinbase/Binance)
- **Data:** CSV embedded inline as JS template literals
- **Tab init:** Lazy (on first activation)
- **File:** Self-contained, opens from file://
