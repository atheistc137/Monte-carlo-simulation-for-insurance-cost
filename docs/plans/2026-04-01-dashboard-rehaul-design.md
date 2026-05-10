# Bitmor Dashboard Design Rehaul

**Date:** 2026-04-01  
**Approach:** B — Surgically modify existing HTML, reshape UI around existing data/logic

## Summary

Transition `bitmor-dashboard.html` from 4-tab layout to 2-view layout matching `bitmor-dashboard.jsx` design. Keep all data (20K lines CSV), live APIs (Coinbase/Binance/Deribit), and calculation logic (Black-Scholes, DataStore, roll-down reconstruction). Hardcode 1 BTC, 12mo term. Stay standalone HTML + Plotly.

## Constraints

- Output: single standalone HTML file
- Charting: Plotly.js (not Recharts)
- Data: all CSV, DataStore, Deribit snapshot/live engine untouched
- Parameters: remove BTC amount selector, price slider, IV slider; hardcode 1 BTC, 12mo
- Tabs: 2 views only ("Cost Calculator", "Roll-Down Research")

## View 1: Cost Calculator

1. Intro block — heading + subtitle
2. Loan origination flow — horizontal steps
3. Section "01" — horizontal parameter bar (BTC spot display, rate slider, DP pills, fixed 12mo)
4. Hero effective price card — gradient, large price, cost breakdown, stacked bar
5. Three detail cards — Upfront / Repayment / Recovery
6. PUT pricing bar — 4-column grid, Deribit data
7. Amortization table

## View 2: Roll-Down Research

1. Context banner — key stats one-liner
2. Hero heading — centered
3. Section "01 — Path Explorer" — nav arrows, Plotly chart, cash flows + summary cards
4. Section "02 — Aggregate Results" — sub-tabs, stats grid, range bar, scatter/distribution toggle
5. Section "03 — Methodology" — collapsible 2×2 grid

## Removed

- Tab 3 (Bitmor Math) — all static method sections
- Tab 4 (Backtest Methodology) — condensed into collapsible in View 2
