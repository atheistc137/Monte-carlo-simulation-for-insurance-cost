# Historical Backtest — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replay every possible loan origination (Apr 2021 – Mar 2025) against actual BTC prices and IV surface data, checking daily whether `BTC + PUT_MTM >= debt + fee`.

**Architecture:** Single backtest engine (`historical_backtest.py`) iterates over origination dates, replays 360 days of loan life using actual prices, computes daily coverage. Report module (`backtest_report.py`) generates interactive Plotly HTML dashboard + CSVs. CLI entry point (`run_backtest.py`).

**Tech Stack:** Python 3.10+, numpy, pandas, plotly, scipy (via imported `bs_price`). Reuses `lookup_iv`, `snap_to_strike`, `apply_slippage`, `bs_price`, `load_surface`, `load_price` from the insurance cost folder via `config.py` path setup.

---

### Task 1: historical_backtest.py — Core backtest engine

**Files:**
- Create: `historical_backtest.py`

**Step 1: Write historical_backtest.py**

```python
"""
Historical backtest: replay every possible loan against actual prices + IV surface.

For each origination date in the backtest window:
  1. Originate loan at that day's spot price (same params as MC)
  2. Walk forward 360 days using actual historical prices
  3. Each day: accrue debt, value PUT via BS with actual IV surface, compute coverage
  4. At monthly boundaries (day 30, 60, ...): deduct payment, attempt PUT rolldown
  5. Record daily coverage ratio
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

import config
from default_model import compute_annuity
from liquidation_waterfall import compute_waterfall
from rolldown_utils import lookup_iv, snap_to_strike, apply_slippage
from liquidation_utils import bs_price, load_surface, load_price

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("backtest")


@dataclass
class DailyCoverage:
    origination_date: pd.Timestamp
    day_in_loan: int
    calendar_date: pd.Timestamp
    spot_0: float
    spot_now: float
    debt: float
    put_K: float
    put_ttm_days: int
    put_iv: float
    put_mtm: float
    put_mtm_after_slippage: float
    btc_value: float
    total_proceeds: float
    total_liabilities: float
    coverage_ratio: float


def _snap_strike_up(raw_strike: float, spot: float) -> float:
    """Snap to exchange grid, rounding UP (ceiling)."""
    return snap_to_strike(raw_strike, spot)


def run_backtest() -> pd.DataFrame:
    """Run the full historical backtest. Returns DataFrame of daily coverage records."""

    # ── Load data ──
    log.info("Loading SVI surface from %s", config.SVI_SURFACE_CSV)
    surface = load_surface(config.SVI_SURFACE_CSV)

    log.info("Loading price data from %s", config.HOURLY_PRICE_CSV)
    price_hourly = load_price(config.HOURLY_PRICE_CSV)
    price_daily = price_hourly.resample("1D").last().dropna()

    # ── Determine backtest window ──
    # IV surface starts Apr 2021, prices go to Mar 2026
    # Loans need 360 days forward, so last origination = last price date - 360 days
    surf_dates = surface.index.get_level_values("date").unique().sort_values()
    first_surface_date = pd.Timestamp(surf_dates[0])
    last_price_date = price_daily.index[-1]
    last_origination = last_price_date - pd.Timedelta(days=config.LOAN_TERM_MONTHS * config.DAYS_PER_MONTH)

    # Origination dates: every day from first surface date to last valid origination
    all_dates = price_daily.loc[first_surface_date:last_origination].index
    log.info("Backtest window: %s to %s (%d origination dates)",
             all_dates[0].strftime("%Y-%m-%d"),
             all_dates[-1].strftime("%Y-%m-%d"),
             len(all_dates))

    total_days = config.LOAN_TERM_MONTHS * config.DAYS_PER_MONTH  # 360

    records: List[dict] = []

    for loan_idx, orig_date in enumerate(all_dates):
        if loan_idx % max(1, len(all_dates) // 20) == 0:
            log.info("Loan %d / %d (originated %s)",
                     loan_idx, len(all_dates), orig_date.strftime("%Y-%m-%d"))

        spot_0 = float(price_daily.loc[orig_date])

        # ── Loan origination ──
        loan_amount = (1 - config.DEPOSIT_PCT / 100) * spot_0
        monthly_payment = compute_annuity(loan_amount, config.SIZING_APR, config.LOAN_TERM_MONTHS)
        initial_put_strike = _snap_strike_up(spot_0 * (1 - config.DEPOSIT_PCT / 100), spot_0)

        # Loan state
        debt = loan_amount
        allocated_btc = 1.0
        put_K = initial_put_strike
        initial_put_tenor_days = 365
        put_tenor_remaining = initial_put_tenor_days

        for day in range(total_days):
            calendar_date = orig_date + pd.Timedelta(days=day)

            # Get actual price — use nearest available if exact date missing
            price_idx = price_daily.index.get_indexer([calendar_date], method="nearest")[0]
            spot_now = float(price_daily.iloc[price_idx])

            # ── Daily debt accrual ──
            debt *= (1 + config.ACCRUAL_APR / 365)

            # ── Monthly boundary: payment + PUT rolldown ──
            if day > 0 and day % config.DAYS_PER_MONTH == 0:
                debt -= monthly_payment
                debt = max(debt, 0.0)

                # PUT rolldown
                month = day // config.DAYS_PER_MONTH
                remaining_months = config.LOAN_TERM_MONTHS - month

                mny_held = put_K / spot_now
                try:
                    iv_held = lookup_iv(surface, calendar_date,
                                        max(put_tenor_remaining, 15), mny_held)
                except (ValueError, KeyError):
                    iv_held = 0.60

                put_T = max(put_tenor_remaining / 365, 1 / 365)
                held_put_value = bs_price(spot_now, put_K, put_T,
                                          config.RISK_FREE_RATE, iv_held, call=False)

                new_raw_strike = debt if debt > 0 else loan_amount * 0.5
                new_K = _snap_strike_up(new_raw_strike, spot_now)
                new_mny = new_K / spot_now
                new_tenor_days = remaining_months * config.DAYS_PER_MONTH
                new_tenor_T = max(new_tenor_days / 365, 1 / 365)

                if new_tenor_days > 0:
                    try:
                        iv_new = lookup_iv(surface, calendar_date,
                                           max(new_tenor_days, 15), new_mny)
                    except (ValueError, KeyError):
                        iv_new = 0.60

                    replacement_cost = bs_price(spot_now, new_K, new_tenor_T,
                                                config.RISK_FREE_RATE, iv_new, call=False)

                    slippage_sell = apply_slippage(held_put_value, mny_held)
                    slippage_buy = apply_slippage(replacement_cost, new_mny)
                    roll_profit = (held_put_value - slippage_sell) - (replacement_cost + slippage_buy)

                    if roll_profit > 0:
                        put_K = new_K
                        put_tenor_remaining = new_tenor_days

            # ── Daily PUT tenor decay ──
            if day > 0:
                put_tenor_remaining -= 1
            put_tenor_remaining = max(put_tenor_remaining, 1)

            # ── Daily coverage check ──
            btc_value = allocated_btc * spot_now
            mny = put_K / spot_now
            put_T = max(put_tenor_remaining / 365, 1 / 365)

            try:
                iv = lookup_iv(surface, calendar_date,
                               max(put_tenor_remaining, 15), mny)
            except (ValueError, KeyError):
                iv = 0.60

            put_mtm = bs_price(spot_now, put_K, put_T,
                               config.RISK_FREE_RATE, iv, call=False)
            slippage = apply_slippage(put_mtm, mny)
            put_mtm_net = max(0, put_mtm - slippage)

            total_proceeds = btc_value + put_mtm_net
            liquidator_fee = config.LIQ_BUFFER * debt
            total_liabilities = debt + liquidator_fee

            if total_liabilities > 0:
                coverage = total_proceeds / total_liabilities
            else:
                coverage = float("inf")

            records.append({
                "origination_date": orig_date,
                "day_in_loan": day,
                "calendar_date": calendar_date,
                "spot_0": spot_0,
                "spot_now": spot_now,
                "debt": debt,
                "put_K": put_K,
                "put_ttm_days": put_tenor_remaining,
                "put_iv": iv,
                "put_mtm": put_mtm,
                "put_mtm_after_slippage": put_mtm_net,
                "btc_value": btc_value,
                "total_proceeds": total_proceeds,
                "total_liabilities": total_liabilities,
                "coverage_ratio": coverage,
            })

    log.info("Backtest complete. %d daily records generated.", len(records))
    return pd.DataFrame(records)
```

**Step 2: Smoke test with a few origination dates**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python3 -c "
import historical_backtest as hb
import config
# Override to just test 3 loans
import pandas as pd
df = hb.run_backtest.__wrapped__() if hasattr(hb.run_backtest, '__wrapped__') else None
" 2>&1 | head -20`

Actually, we need a real smoke test. We'll test by temporarily limiting the date range:

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python3 -c "
from historical_backtest import run_backtest
import pandas as pd
df = run_backtest()
print(f'Records: {len(df)}')
print(f'Origination dates: {df[\"origination_date\"].nunique()}')
print(f'Min coverage: {df[\"coverage_ratio\"].min():.4f}')
print(f'Columns: {list(df.columns)}')
print(df.head(3).to_string())
" 2>&1 | tail -20`

Expected: Runs without error, shows coverage records, min coverage value.

Note: The full run will take several minutes due to ~525k BS calls. If it's too slow, we'll optimize in Task 4.

**Step 3: Commit**

```bash
git add historical_backtest.py
git commit -m "feat: add historical backtest engine with daily coverage checks"
```

---

### Task 2: backtest_report.py — HTML report, CSVs, console summary

**Files:**
- Create: `backtest_report.py`

**Step 1: Write backtest_report.py**

```python
"""
Backtest reporting: interactive Plotly HTML dashboard + CSVs + console summary.

Uses Bitmor design language: dark theme (#030916), persimmon accent (#F25E13),
Bricolage Grotesque + IBM Plex Mono fonts, card-based layout.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

import config

log = logging.getLogger("backtest_report")

# ── Bitmor design tokens ──
COLORS = {
    "bg": "#030916",
    "bg_card": "#0a1428",
    "border": "#1a2a4a",
    "accent": "#F25E13",
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#eab308",
    "text": "#e8ecf4",
    "text_dim": "#7a8ba8",
    "text_muted": "#4a5d7a",
    "white": "#ffffff",
}

PLOTLY_LAYOUT = dict(
    paper_bgcolor=COLORS["bg_card"],
    plot_bgcolor=COLORS["bg"],
    font=dict(family="IBM Plex Mono, monospace", color=COLORS["text"], size=12),
    xaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
    yaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
    margin=dict(l=60, r=40, t=50, b=50),
)


def compute_worst_by_loan(df: pd.DataFrame) -> pd.DataFrame:
    """For each loan, find the day with minimum coverage ratio."""
    finite = df[df["coverage_ratio"] < float("inf")].copy()
    if finite.empty:
        return pd.DataFrame()

    idx = finite.groupby("origination_date")["coverage_ratio"].idxmin()
    worst = finite.loc[idx].copy()
    worst["drawdown_pct"] = (worst["spot_now"] - worst["spot_0"]) / worst["spot_0"] * 100
    worst = worst.sort_values("coverage_ratio").reset_index(drop=True)
    return worst


def compute_summary(df: pd.DataFrame, worst: pd.DataFrame) -> dict:
    """Single-row summary stats."""
    n_loans = df["origination_date"].nunique()
    finite = df[df["coverage_ratio"] < float("inf")]

    breaches = finite[finite["coverage_ratio"] < 1.0]
    n_breach_days = len(breaches)
    n_breach_loans = breaches["origination_date"].nunique() if n_breach_days > 0 else 0

    summary = {
        "total_loans": n_loans,
        "total_daily_checks": len(df),
        "any_breach": n_breach_days > 0,
        "n_breach_days": n_breach_days,
        "n_breach_loans": n_breach_loans,
        "worst_coverage": float(finite["coverage_ratio"].min()) if len(finite) > 0 else None,
        "mean_min_coverage": float(worst["coverage_ratio"].mean()) if len(worst) > 0 else None,
        "median_min_coverage": float(worst["coverage_ratio"].median()) if len(worst) > 0 else None,
        "p5_min_coverage": float(worst["coverage_ratio"].quantile(0.05)) if len(worst) > 0 else None,
    }

    if n_breach_days > 0:
        worst_row = finite.loc[finite["coverage_ratio"].idxmin()]
        summary["worst_origination"] = str(worst_row["origination_date"])
        summary["worst_day_in_loan"] = int(worst_row["day_in_loan"])
        summary["worst_calendar_date"] = str(worst_row["calendar_date"])
        summary["worst_spot"] = float(worst_row["spot_now"])
        summary["worst_debt"] = float(worst_row["debt"])
    elif len(finite) > 0:
        worst_row = finite.loc[finite["coverage_ratio"].idxmin()]
        summary["worst_origination"] = str(worst_row["origination_date"])
        summary["worst_day_in_loan"] = int(worst_row["day_in_loan"])
        summary["worst_calendar_date"] = str(worst_row["calendar_date"])

    return summary


def _build_chart1_html(worst: pd.DataFrame, price_daily: pd.Series) -> str:
    """Chart 1: Min-coverage time series + BTC price overlay."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=worst["origination_date"],
            y=worst["coverage_ratio"],
            mode="markers",
            marker=dict(
                size=4,
                color=worst["coverage_ratio"],
                colorscale=[[0, COLORS["red"]], [0.5, COLORS["yellow"]], [1, COLORS["green"]]],
                cmin=0.8,
                cmax=3.0,
            ),
            name="Min Coverage",
            hovertemplate=(
                "Originated: %{x|%Y-%m-%d}<br>"
                "Min Coverage: %{y:.3f}<br>"
                "<extra></extra>"
            ),
        ),
        secondary_y=False,
    )

    # Break-even line
    fig.add_hline(y=1.0, line_dash="dash", line_color=COLORS["red"],
                  line_width=2, secondary_y=False,
                  annotation_text="Break-even", annotation_font_color=COLORS["red"])

    # BTC price overlay
    price_range = price_daily.loc[worst["origination_date"].min():worst["origination_date"].max()]
    fig.add_trace(
        go.Scatter(
            x=price_range.index,
            y=price_range.values,
            mode="lines",
            line=dict(color=COLORS["accent"], width=1.5),
            name="BTC Price",
            opacity=0.6,
        ),
        secondary_y=True,
    )

    layout = {**PLOTLY_LAYOUT}
    fig.update_layout(
        **layout,
        title=dict(text="Minimum Coverage Ratio by Loan Vintage", font=dict(size=16)),
        yaxis=dict(title="Coverage Ratio", **{k: v for k, v in PLOTLY_LAYOUT["yaxis"].items()}),
        yaxis2=dict(title="BTC Price ($)", gridcolor=COLORS["border"],
                    zerolinecolor=COLORS["border"]),
        xaxis=dict(title="Origination Date", **{k: v for k, v in PLOTLY_LAYOUT["xaxis"].items()}),
        showlegend=True,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=COLORS["text_dim"])),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_chart2_html(df: pd.DataFrame) -> str:
    """Chart 2: Coverage vs spot drawdown scatter."""
    import plotly.graph_objects as go

    finite = df[df["coverage_ratio"] < float("inf")].copy()
    # Sample if too many points for browser performance
    if len(finite) > 50_000:
        finite = finite.sample(50_000, random_state=42)

    finite["drawdown_pct"] = (finite["spot_now"] - finite["spot_0"]) / finite["spot_0"] * 100

    fig = go.Figure()
    fig.add_trace(go.Scattergl(
        x=finite["drawdown_pct"],
        y=finite["coverage_ratio"],
        mode="markers",
        marker=dict(
            size=2,
            color=finite["coverage_ratio"],
            colorscale=[[0, COLORS["red"]], [0.5, COLORS["yellow"]], [1, COLORS["green"]]],
            cmin=0.8,
            cmax=3.0,
            opacity=0.4,
        ),
        hovertemplate=(
            "Drawdown: %{x:.1f}%<br>"
            "Coverage: %{y:.3f}<br>"
            "<extra></extra>"
        ),
    ))

    fig.add_hline(y=1.0, line_dash="dash", line_color=COLORS["red"], line_width=2,
                  annotation_text="Break-even", annotation_font_color=COLORS["red"])

    layout = {**PLOTLY_LAYOUT}
    fig.update_layout(
        **layout,
        title=dict(text="Coverage Ratio vs Spot Drawdown", font=dict(size=16)),
        xaxis=dict(title="Price Change from Origination (%)",
                   **{k: v for k, v in PLOTLY_LAYOUT["xaxis"].items()}),
        yaxis=dict(title="Coverage Ratio",
                   **{k: v for k, v in PLOTLY_LAYOUT["yaxis"].items()}),
        showlegend=False,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_chart3_html(df: pd.DataFrame, worst: pd.DataFrame, n_worst: int = 10) -> str:
    """Chart 3: Worst-N loan lifecycle curves."""
    import plotly.graph_objects as go

    worst_loans = worst.head(n_worst)["origination_date"].values
    fig = go.Figure()

    colors_cycle = [COLORS["red"], COLORS["yellow"], COLORS["accent"],
                    "#a855f7", "#3b82f6", "#14b8a6", "#f472b6",
                    "#84cc16", "#06b6d4", "#f59e0b"]

    for i, orig in enumerate(worst_loans):
        loan_df = df[df["origination_date"] == orig].sort_values("day_in_loan")
        finite = loan_df[loan_df["coverage_ratio"] < float("inf")]
        orig_str = pd.Timestamp(orig).strftime("%Y-%m-%d")
        min_cov = finite["coverage_ratio"].min() if len(finite) > 0 else 0

        fig.add_trace(go.Scatter(
            x=finite["day_in_loan"],
            y=finite["coverage_ratio"],
            mode="lines",
            name=f"{orig_str} (min: {min_cov:.2f})",
            line=dict(color=colors_cycle[i % len(colors_cycle)], width=1.5),
            hovertemplate=(
                f"Loan: {orig_str}<br>"
                "Day: %{x}<br>"
                "Coverage: %{y:.3f}<br>"
                "<extra></extra>"
            ),
        ))

    fig.add_hline(y=1.0, line_dash="dash", line_color=COLORS["red"], line_width=2,
                  annotation_text="Break-even", annotation_font_color=COLORS["red"])

    layout = {**PLOTLY_LAYOUT}
    fig.update_layout(
        **layout,
        title=dict(text="Coverage Over Loan Life — 10 Most Stressed Loans", font=dict(size=16)),
        xaxis=dict(title="Day in Loan",
                   **{k: v for k, v in PLOTLY_LAYOUT["xaxis"].items()}),
        yaxis=dict(title="Coverage Ratio",
                   **{k: v for k, v in PLOTLY_LAYOUT["yaxis"].items()}),
        showlegend=True,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=COLORS["text_dim"], size=10)),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


# ── Known stress events for overlay table ──
STRESS_EVENTS = [
    {"name": "LUNA / UST collapse", "start": "2022-05-01", "end": "2022-05-31"},
    {"name": "3AC / Celsius contagion", "start": "2022-06-01", "end": "2022-06-30"},
    {"name": "FTX collapse", "start": "2022-11-01", "end": "2022-11-30"},
]


def _build_stress_table_html(df: pd.DataFrame, worst: pd.DataFrame) -> str:
    """Build an HTML table showing coverage for loans active during known stress events."""
    rows_html = ""
    for evt in STRESS_EVENTS:
        start = pd.Timestamp(evt["start"])
        end = pd.Timestamp(evt["end"])

        # Loans active during event: originated before event end, and still running at event start
        # A loan originated on date D is active on days D .. D+359
        active = df[
            (df["calendar_date"] >= start) &
            (df["calendar_date"] <= end)
        ]
        if active.empty:
            rows_html += f"""
            <tr>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border);">{evt["name"]}</td>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border);">{evt["start"][:7]}</td>
              <td colspan="4" style="padding:10px 14px; border-bottom:1px solid var(--border); color:var(--text-dim);">No active loans</td>
            </tr>"""
            continue

        n_active = active["origination_date"].nunique()
        worst_cov = active["coverage_ratio"]
        worst_cov_finite = worst_cov[worst_cov < float("inf")]
        min_cov = float(worst_cov_finite.min()) if len(worst_cov_finite) > 0 else float("inf")
        median_cov = float(worst_cov_finite.median()) if len(worst_cov_finite) > 0 else float("inf")
        n_breach = int((worst_cov_finite < 1.0).sum())

        cov_color = COLORS["red"] if min_cov < 1.0 else (COLORS["yellow"] if min_cov < 1.2 else COLORS["green"])

        rows_html += f"""
            <tr>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border); font-weight:500;">{evt["name"]}</td>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border); font-family:var(--mono);">{evt["start"][:7]}</td>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border); font-family:var(--mono);">{n_active:,}</td>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border); font-family:var(--mono); color:{cov_color};">{min_cov:.3f}</td>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border); font-family:var(--mono);">{median_cov:.3f}</td>
              <td style="padding:10px 14px; border-bottom:1px solid var(--border); font-family:var(--mono); color:{'var(--red)' if n_breach > 0 else 'var(--green)'};">{n_breach:,}</td>
            </tr>"""

    return f"""
    <table style="width:100%; border-collapse:collapse; font-size:13px;">
      <thead>
        <tr style="text-align:left;">
          <th style="padding:10px 14px; border-bottom:2px solid var(--border); color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:0.1em;">Event</th>
          <th style="padding:10px 14px; border-bottom:2px solid var(--border); color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:0.1em;">Period</th>
          <th style="padding:10px 14px; border-bottom:2px solid var(--border); color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:0.1em;">Active Loans</th>
          <th style="padding:10px 14px; border-bottom:2px solid var(--border); color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:0.1em;">Min Coverage</th>
          <th style="padding:10px 14px; border-bottom:2px solid var(--border); color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:0.1em;">Median Coverage</th>
          <th style="padding:10px 14px; border-bottom:2px solid var(--border); color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:0.1em;">Breach Days</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>"""


def _build_html_report(summary: dict, chart1: str, chart2: str, chart3: str,
                       stress_table: str) -> str:
    """Build full HTML report with Bitmor design language."""
    verdict = "PASS — No coverage breaches" if not summary["any_breach"] else f"FAIL — {summary['n_breach_loans']} loans breached"
    verdict_color = COLORS["green"] if not summary["any_breach"] else COLORS["red"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Bitmor — Historical Backtest</title>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,300;12..96,400;12..96,500;12..96,700;12..96,800&family=IBM+Plex+Mono:wght@300;400;500&display=swap" rel="stylesheet" />
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: {COLORS["bg"]};
    --bg-card: {COLORS["bg_card"]};
    --border: {COLORS["border"]};
    --accent: {COLORS["accent"]};
    --green: {COLORS["green"]};
    --red: {COLORS["red"]};
    --text: {COLORS["text"]};
    --text-dim: {COLORS["text_dim"]};
    --text-muted: {COLORS["text_muted"]};
    --white: {COLORS["white"]};
    --font: 'Bricolage Grotesque', sans-serif;
    --mono: 'IBM Plex Mono', monospace;
  }}
  html {{ scroll-behavior: smooth; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    min-height: 100vh;
    line-height: 1.6;
  }}
  body::before {{
    content: '';
    position: fixed; inset: 0;
    background-image:
      repeating-linear-gradient(0deg, transparent, transparent 59px, rgba(242,94,19,0.03) 59px, rgba(242,94,19,0.03) 60px),
      repeating-linear-gradient(90deg, transparent, transparent 59px, rgba(242,94,19,0.03) 59px, rgba(242,94,19,0.03) 60px);
    pointer-events: none; z-index: 0;
  }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 0 24px 80px; position: relative; z-index: 1; }}
  .top-nav {{
    position: sticky; top: 0; z-index: 100;
    background: rgba(3,9,22,0.93); backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border); padding: 16px 32px;
    display: flex; align-items: center; gap: 10px;
  }}
  .nav-logo-mark {{
    width: 28px; height: 28px; border-radius: 6px;
    background: var(--accent); display: flex; align-items: center;
    justify-content: center; font-size: 14px; font-weight: 800; color: var(--white);
  }}
  .nav-logo-text {{ font-size: 15px; font-weight: 600; color: var(--text); }}
  .nav-subtitle {{ font-size: 13px; color: var(--text-dim); margin-left: 8px; }}
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 28px;
    margin-bottom: 24px;
  }}
  .stat-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
  }}
  .stat-box {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }}
  .stat-label {{
    font-size: 10px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 6px;
  }}
  .stat-value {{
    font-size: 22px; font-weight: 700;
    font-family: var(--mono);
  }}
  .stat-sub {{ font-size: 11px; color: var(--text-dim); margin-top: 4px; }}
  .section-title {{
    font-size: 10px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 16px;
  }}
  .verdict {{
    font-size: 18px; font-weight: 700;
    padding: 16px 24px; border-radius: 8px;
    text-align: center; margin-bottom: 24px;
  }}
</style>
</head>
<body>
<nav class="top-nav">
  <div class="nav-logo-mark">B</div>
  <span class="nav-logo-text">Bitmor</span>
  <span class="nav-subtitle">Historical Backtest — Coverage Analysis</span>
</nav>
<div class="container">

  <div style="margin-top:32px;">
    <div class="verdict" style="background: rgba({'34,197,94' if not summary['any_breach'] else '239,68,68'},0.12); border: 1px solid {verdict_color}; color: {verdict_color};">
      {verdict}
    </div>
  </div>

  <div class="card">
    <div class="section-title">Key Metrics</div>
    <div class="stat-grid">
      <div class="stat-box">
        <div class="stat-label">Total Loans</div>
        <div class="stat-value" style="color: var(--text);">{summary['total_loans']:,}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Daily Checks</div>
        <div class="stat-value" style="color: var(--text);">{summary['total_daily_checks']:,}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Worst Coverage</div>
        <div class="stat-value" style="color: {COLORS['red'] if summary.get('worst_coverage', 2) < 1.0 else COLORS['green']};">{summary.get('worst_coverage', 0):.3f}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Median Min-Coverage</div>
        <div class="stat-value" style="color: var(--green);">{summary.get('median_min_coverage', 0):.3f}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">5th Percentile</div>
        <div class="stat-value" style="color: var(--yellow);">{summary.get('p5_min_coverage', 0):.3f}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Breach Days</div>
        <div class="stat-value" style="color: {'var(--green)' if summary['n_breach_days'] == 0 else 'var(--red)'};">{summary['n_breach_days']:,}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="section-title">Min Coverage by Loan Vintage</div>
    {chart1}
  </div>

  <div class="card">
    <div class="section-title">Coverage vs Spot Drawdown</div>
    {chart2}
  </div>

  <div class="card">
    <div class="section-title">Most Stressed Loans — Coverage Over Loan Life</div>
    {chart3}
  </div>

  <div class="card">
    <div class="section-title">Coverage During Known Stress Events</div>
    {stress_table}
  </div>

</div>
</body>
</html>"""


def save_backtest_results(df: pd.DataFrame,
                          output_dir: Path | None = None) -> None:
    """Save CSVs, HTML report, and print console summary."""
    if output_dir is None:
        output_dir = config.RESULTS_DIR / "backtest"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Load price for chart overlay ──
    price_hourly = load_price(config.HOURLY_PRICE_CSV)
    price_daily = price_hourly.resample("1D").last().dropna()

    # ── Compute aggregations ──
    worst = compute_worst_by_loan(df)
    summary = compute_summary(df, worst)

    # ── CSVs ──
    df.to_csv(output_dir / "daily_coverage.csv", index=False)
    log.info("Saved daily_coverage.csv (%d rows)", len(df))

    if len(worst) > 0:
        worst.to_csv(output_dir / "worst_by_loan.csv", index=False)
        log.info("Saved worst_by_loan.csv (%d rows)", len(worst))

    pd.DataFrame([summary]).to_csv(output_dir / "backtest_summary.csv", index=False)
    log.info("Saved backtest_summary.csv")

    # ── HTML report ──
    chart1 = _build_chart1_html(worst, price_daily)
    chart2 = _build_chart2_html(df)
    chart3 = _build_chart3_html(df, worst)
    stress_table = _build_stress_table_html(df, worst)
    html = _build_html_report(summary, chart1, chart2, chart3, stress_table)

    (output_dir / "backtest_report.html").write_text(html, encoding="utf-8")
    log.info("Saved backtest_report.html")

    # ── Console summary ──
    print("\n" + "=" * 60)
    print("  HISTORICAL BACKTEST — COVERAGE ANALYSIS")
    print("=" * 60)
    print(f"  Loans tested        : {summary['total_loans']:,}")
    print(f"  Daily checks        : {summary['total_daily_checks']:,}")
    print(f"  Worst coverage      : {summary.get('worst_coverage', 'N/A'):.4f}" if summary.get('worst_coverage') else "  Worst coverage      : N/A")
    print(f"  Median min-coverage : {summary.get('median_min_coverage', 'N/A'):.4f}" if summary.get('median_min_coverage') else "  Median min-coverage : N/A")
    print(f"  5th percentile      : {summary.get('p5_min_coverage', 'N/A'):.4f}" if summary.get('p5_min_coverage') else "  5th percentile      : N/A")
    print(f"  Breach days         : {summary['n_breach_days']:,}")
    print(f"  Breach loans        : {summary['n_breach_loans']:,}")
    if summary["any_breach"]:
        print(f"  Worst loan orig     : {summary.get('worst_origination', 'N/A')}")
        print(f"  Worst day in loan   : {summary.get('worst_day_in_loan', 'N/A')}")
        print(f"  VERDICT             : ** FAIL **")
    else:
        print(f"  VERDICT             : ** PASS — No breaches **")
    print("=" * 60 + "\n")
```

**Step 2: Verify plotly is installed**

Run: `python3 -c "import plotly; print(plotly.__version__)"`
If not installed: `pip install plotly`

**Step 3: Commit**

```bash
git add backtest_report.py
git commit -m "feat: add backtest report with interactive Plotly HTML dashboard"
```

---

### Task 3: run_backtest.py — CLI entry point

**Files:**
- Create: `run_backtest.py`

**Step 1: Write run_backtest.py**

```python
#!/usr/bin/env python3
"""
Entry point: run the historical backtest and produce reports.

Usage:
    python run_backtest.py               # full backtest (~1,460 loans)
    python run_backtest.py --limit 50    # quick test (first 50 loans only)
"""
from __future__ import annotations

import argparse
import logging

import config
from historical_backtest import run_backtest
from backtest_report import save_backtest_results
from liquidation_utils import load_price

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def main():
    parser = argparse.ArgumentParser("Historical Backtest — Coverage Analysis")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit to first N origination dates (0 = all)")
    args = parser.parse_args()

    df = run_backtest(limit=args.limit)
    save_backtest_results(df)


if __name__ == "__main__":
    main()
```

**Step 2: Add `limit` parameter to `run_backtest()`**

Update the function signature in `historical_backtest.py` to accept `limit`:

Change `def run_backtest() -> pd.DataFrame:` to `def run_backtest(limit: int = 0) -> pd.DataFrame:`

And after `all_dates = price_daily.loc[first_surface_date:last_origination].index`, add:
```python
    if limit > 0:
        all_dates = all_dates[:limit]
```

**Step 3: Quick test with 5 loans**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python3 run_backtest.py --limit 5`
Expected: Runs quickly, prints summary, creates files in `results/backtest/`

**Step 4: Verify output files**

Run: `ls -la results/backtest/`
Expected: `daily_coverage.csv`, `worst_by_loan.csv`, `backtest_summary.csv`, `backtest_report.html`

**Step 5: Commit**

```bash
git add run_backtest.py
git commit -m "feat: add CLI entry point for historical backtest"
```

---

### Task 4: Performance optimization (if needed)

**Files:**
- Modify: `historical_backtest.py`

The full backtest is ~1,460 loans × 360 days = ~525k daily checks, each requiring a BS call + IV lookup. If the full run takes >10 minutes, optimize:

**Step 1: Profile the full run**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && time python3 run_backtest.py --limit 50`

Measure time per loan. If >1s/loan, we need optimization.

**Step 2: Vectorize if needed**

The main bottleneck will be the inner loop (360 BS calls per loan). Potential optimizations:
- Pre-compute all daily prices for the full backtest window into a numpy array for O(1) access
- Batch BS calls using vectorized numpy operations
- Pre-compute debt schedule (it's deterministic per loan — only depends on spot_0)

Only apply if Step 1 shows >10 min projected runtime.

**Step 3: Commit any optimizations**

```bash
git add historical_backtest.py
git commit -m "perf: optimize backtest inner loop"
```

---

### Task 5: Full backtest run + validation

**Step 1: Run full backtest**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python3 run_backtest.py`

Expected: Completes, prints summary with pass/fail verdict.

**Step 2: Sanity check outputs**

- Open `results/backtest/backtest_report.html` in browser
- Verify all 3 charts render correctly
- Check that loans originated before May 2022 crash and Nov 2022 (FTX) show lowest coverage
- Coverage should always be > 1.0 if the PUT hedge works historically
- Scatter plot should show coverage declining with drawdown but staying above 1.0

**Step 3: Review worst-case loans**

Run: `python3 -c "import pandas as pd; w = pd.read_csv('results/backtest/worst_by_loan.csv'); print(w.head(20).to_string())"`

Check: Are the worst loans clustered around known crash dates?

**Step 4: Commit results**

```bash
git add results/backtest/
git commit -m "results: historical backtest — full coverage analysis"
```
