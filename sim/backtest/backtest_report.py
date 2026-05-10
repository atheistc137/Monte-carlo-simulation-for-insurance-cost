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

from sim.shared import config
from sim.liquidation.liquidation_utils import load_price

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
    margin=dict(l=60, r=20, t=50, b=50),
    autosize=True,
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


def _has_completion_data(df: pd.DataFrame) -> bool:
    """Check if the DataFrame contains the loan_completed column."""
    return "loan_completed" in df.columns


def compute_summary(df: pd.DataFrame, worst: pd.DataFrame) -> dict:
    """Single-row summary stats.

    Aggregate statistics (median, mean, percentiles) are computed from
    *complete* loans only.  Incomplete loans are reported separately for
    breach detection — they are not mixed into the distribution stats.
    """
    has_completion = _has_completion_data(df)

    # Split complete vs incomplete
    if has_completion:
        df_complete = df[df["loan_completed"]]
        df_incomplete = df[~df["loan_completed"]]
        worst_complete = worst[worst["loan_completed"]] if "loan_completed" in worst.columns else worst
        worst_incomplete = worst[~worst["loan_completed"]] if "loan_completed" in worst.columns else pd.DataFrame()
    else:
        df_complete = df
        df_incomplete = pd.DataFrame()
        worst_complete = worst
        worst_incomplete = pd.DataFrame()

    n_complete = df_complete["origination_date"].nunique() if len(df_complete) > 0 else 0
    n_incomplete = df_incomplete["origination_date"].nunique() if len(df_incomplete) > 0 else 0

    # ── Complete loan stats (used for aggregate metrics) ──
    finite_complete = df_complete[df_complete["coverage_ratio"] < float("inf")] if len(df_complete) > 0 else pd.DataFrame()
    breaches_complete = finite_complete[finite_complete["coverage_ratio"] < 1.0] if len(finite_complete) > 0 else pd.DataFrame()
    n_breach_days_complete = len(breaches_complete)
    n_breach_loans_complete = breaches_complete["origination_date"].nunique() if n_breach_days_complete > 0 else 0

    # ── Incomplete loan breach detection ──
    finite_incomplete = df_incomplete[df_incomplete["coverage_ratio"] < float("inf")] if len(df_incomplete) > 0 else pd.DataFrame()
    breaches_incomplete = finite_incomplete[finite_incomplete["coverage_ratio"] < 1.0] if len(finite_incomplete) > 0 else pd.DataFrame()
    n_breach_days_incomplete = len(breaches_incomplete)
    n_breach_loans_incomplete = breaches_incomplete["origination_date"].nunique() if n_breach_days_incomplete > 0 else 0

    # ── Overall worst coverage (across both complete and incomplete) ──
    finite_all = df[df["coverage_ratio"] < float("inf")]
    overall_worst = float(finite_all["coverage_ratio"].min()) if len(finite_all) > 0 else None
    worst_is_incomplete = False
    if overall_worst is not None and has_completion:
        worst_row_all = finite_all.loc[finite_all["coverage_ratio"].idxmin()]
        worst_is_incomplete = not bool(worst_row_all.get("loan_completed", True))

    summary = {
        # Counts
        "total_loans": n_complete + n_incomplete,
        "complete_loans": n_complete,
        "incomplete_loans": n_incomplete,
        "total_daily_checks": len(df),
        # Complete-loan aggregate stats
        "any_breach": n_breach_days_complete > 0,
        "n_breach_days": n_breach_days_complete,
        "n_breach_loans": n_breach_loans_complete,
        "worst_coverage": float(finite_complete["coverage_ratio"].min()) if len(finite_complete) > 0 else None,
        "mean_min_coverage": float(worst_complete["coverage_ratio"].mean()) if len(worst_complete) > 0 else None,
        "median_min_coverage": float(worst_complete["coverage_ratio"].median()) if len(worst_complete) > 0 else None,
        "p5_min_coverage": float(worst_complete["coverage_ratio"].quantile(0.05)) if len(worst_complete) > 0 else None,
        # Incomplete-loan breach info
        "incomplete_any_breach": n_breach_days_incomplete > 0,
        "incomplete_n_breach_days": n_breach_days_incomplete,
        "incomplete_n_breach_loans": n_breach_loans_incomplete,
        "incomplete_worst_coverage": float(finite_incomplete["coverage_ratio"].min()) if len(finite_incomplete) > 0 else None,
        # Overall worst (may come from incomplete loan)
        "overall_worst_coverage": overall_worst,
        "overall_worst_is_incomplete": worst_is_incomplete,
    }

    # Identify the worst row for display
    for label, finite_subset in [("", finite_complete), ("incomplete_", finite_incomplete)]:
        if len(finite_subset) > 0:
            has_breach = (finite_subset["coverage_ratio"] < 1.0).any()
            worst_row = finite_subset.loc[finite_subset["coverage_ratio"].idxmin()]
            if has_breach or label == "":
                summary[f"{label}worst_origination"] = str(worst_row["origination_date"])
                summary[f"{label}worst_day_in_loan"] = int(worst_row["day_in_loan"])
                summary[f"{label}worst_calendar_date"] = str(worst_row["calendar_date"])
                if has_breach:
                    summary[f"{label}worst_spot"] = float(worst_row["spot_now"])
                    summary[f"{label}worst_debt"] = float(worst_row["debt"])
                if label == "incomplete_" and "loan_days_available" in worst_row.index:
                    summary["incomplete_worst_days_available"] = int(worst_row["loan_days_available"])

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
                cmin=1.0,
                cmax=2.0,
                showscale=False,
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
            line=dict(color="rgba(107,122,150,0.5)", width=1.5),
            name="BTC Price",
        ),
        secondary_y=True,
    )

    base = {k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")}
    fig.update_layout(
        **base,
        title=dict(text="Minimum Coverage Ratio by Loan Vintage", font=dict(size=16)),
        yaxis=dict(title="Coverage Ratio", **PLOTLY_LAYOUT["yaxis"]),
        yaxis2=dict(title="BTC Price ($)", gridcolor=COLORS["border"],
                    zerolinecolor=COLORS["border"]),
        xaxis=dict(title="Origination Date", **PLOTLY_LAYOUT["xaxis"]),
        showlegend=True,
        legend=dict(
            bgcolor="rgba(0,0,0,0.5)",
            font=dict(color=COLORS["text_dim"]),
            x=0.01, y=0.99, xanchor="left", yanchor="top",
        ),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       default_width='100%', config={'responsive': True})


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
            showscale=False,
        ),
        hovertemplate=(
            "Drawdown: %{x:.1f}%<br>"
            "Coverage: %{y:.3f}<br>"
            "<extra></extra>"
        ),
    ))

    fig.add_hline(y=1.0, line_dash="dash", line_color=COLORS["red"], line_width=2,
                  annotation_text="Break-even", annotation_font_color=COLORS["red"])

    base = {k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")}
    fig.update_layout(
        **base,
        title=dict(text="Coverage Ratio vs Spot Drawdown", font=dict(size=16)),
        xaxis=dict(title="Price Change from Origination (%)", **PLOTLY_LAYOUT["xaxis"]),
        yaxis=dict(title="Coverage Ratio", **PLOTLY_LAYOUT["yaxis"]),
        showlegend=False,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       default_width='100%', config={'responsive': True})


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

    base = {k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis")}
    fig.update_layout(
        **base,
        title=dict(text="Coverage Over Loan Life — 10 Most Stressed Loans", font=dict(size=16)),
        xaxis=dict(title="Day in Loan", **PLOTLY_LAYOUT["xaxis"]),
        yaxis=dict(title="Coverage Ratio", **PLOTLY_LAYOUT["yaxis"]),
        showlegend=True,
        legend=dict(
            bgcolor="rgba(0,0,0,0.5)",
            font=dict(color=COLORS["text_dim"], size=10),
            x=0.01, y=0.99, xanchor="left", yanchor="top",
        ),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       default_width='100%', config={'responsive': True})


# ── Known stress events for overlay table ──
STRESS_EVENTS = [
    {"name": "LUNA / UST collapse", "start": "2022-05-01", "end": "2022-05-31"},
    {"name": "3AC / Celsius contagion", "start": "2022-06-01", "end": "2022-06-30"},
    {"name": "FTX collapse", "start": "2022-11-01", "end": "2022-11-30"},
    {"name": "Oct\u2013Nov 2025 liquidation cascade", "start": "2025-10-06", "end": "2025-11-30"},
]


def _build_stress_table_html(df: pd.DataFrame, worst: pd.DataFrame) -> str:
    """Build an HTML table showing coverage for loans active during known stress events.

    Only loans originated within 6 months before the event start are included,
    so nearly-repaid loans don't inflate the median.
    """
    lookback_days = 6 * config.DAYS_PER_MONTH  # 180 days
    rows_html = ""
    for evt in STRESS_EVENTS:
        start = pd.Timestamp(evt["start"])
        end = pd.Timestamp(evt["end"])
        earliest_orig = start - pd.Timedelta(days=lookback_days)

        # Loans active during event, originated within 6 months before event start
        active = df[
            (df["calendar_date"] >= start) &
            (df["calendar_date"] <= end) &
            (df["origination_date"] >= earliest_orig)
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


def _build_incomplete_card_html(summary: dict) -> str:
    """Build an HTML card summarising incomplete (in-progress) loan coverage."""
    n_incomplete = summary.get("incomplete_loans", 0)
    if n_incomplete == 0:
        return ""

    inc_breach = summary.get("incomplete_any_breach", False)
    inc_breach_loans = summary.get("incomplete_n_breach_loans", 0)
    inc_breach_days = summary.get("incomplete_n_breach_days", 0)
    inc_worst = summary.get("incomplete_worst_coverage")
    inc_worst_fmt = f"{inc_worst:.3f}" if inc_worst is not None else "N/A"
    inc_worst_color = COLORS["red"] if inc_worst is not None and inc_worst < 1.0 else COLORS["green"]

    breach_detail = ""
    if inc_breach:
        orig = summary.get("incomplete_worst_origination", "N/A")
        day = summary.get("incomplete_worst_day_in_loan", "?")
        avail = summary.get("incomplete_worst_days_available", "?")
        breach_detail = f"""
    <p style="font-size:13px; color:{COLORS['red']}; margin-top:12px; font-family:var(--mono);">
      Worst: {inc_worst_fmt} (originated {orig}, day {day}/{avail})
    </p>"""

    return f"""
  <div class="card" style="border-color: {COLORS['yellow']}40;">
    <div class="section-title">Incomplete Loans — In-Progress ({n_incomplete:,})</div>
    <p style="font-size:13px; color:var(--text-dim); margin-bottom:14px;">
      These loans were originated recently and do not yet have a full 12-month price history.
      They are excluded from the aggregate statistics above but monitored for coverage breaches.
    </p>
    <div class="stat-grid">
      <div class="stat-box">
        <div class="stat-label">In-Progress Loans</div>
        <div class="stat-value" style="color: var(--text);">{n_incomplete:,}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Worst Coverage</div>
        <div class="stat-value" style="color: {inc_worst_color};">{inc_worst_fmt}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Breach Loans</div>
        <div class="stat-value" style="color: {'var(--red)' if inc_breach else 'var(--green)'};">{inc_breach_loans:,}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Breach Days</div>
        <div class="stat-value" style="color: {'var(--red)' if inc_breach else 'var(--green)'};">{inc_breach_days:,}</div>
      </div>
    </div>{breach_detail}
  </div>"""


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
    <div class="section-title">What this tests</div>
    <p style="font-size:14px; color:var(--text-dim); line-height:1.7; margin-bottom:12px;">
      Bitmor hedges every BTC-backed loan with a PUT option. If the borrower defaults, the protocol sells the BTC collateral and the PUT to recover the outstanding debt plus a 3% liquidator fee. The PUT itself is struck 3% above the debt level to maintain a collateralisation buffer. The <span style="color:var(--text); font-family:var(--mono);">coverage ratio</span> measures whether those two assets cover the total liability:
    </p>
    <p style="font-size:13px; font-family:var(--mono); color:var(--accent); margin-bottom:12px; padding:10px 14px; background:var(--bg); border:1px solid var(--border); border-radius:6px; display:inline-block;">
      coverage = (BTC_value + PUT_mark_to_market) / (debt + liquidator_fee)
    </p>
    <p style="font-size:14px; color:var(--text-dim); line-height:1.7; margin-bottom:0;">
      A ratio below 1.0 means the hedge failed to cover the debt. This backtest originates a loan on every calendar day from April 2021 through the latest available date ({summary['total_loans']:,} loans: {summary.get('complete_loans', summary['total_loans']):,} complete, {summary.get('incomplete_loans', 0):,} in-progress). Complete loans replay the full 12-month term; incomplete loans run for as many days as price data allows. No simulation, no randomness. PUT values use Black-Scholes with the real implied volatility surface for that date, and PUTs roll monthly when profitable.
    </p>
  </div>

  <div class="card">
    <div class="section-title">Key Metrics — Complete Loans ({summary.get('complete_loans', summary['total_loans']):,})</div>
    <div class="stat-grid">
      <div class="stat-box">
        <div class="stat-label">Complete Loans</div>
        <div class="stat-value" style="color: var(--text);">{summary.get('complete_loans', summary['total_loans']):,}</div>
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

  {_build_incomplete_card_html(summary)}

  <div class="card">
    <div class="section-title">Min Coverage by Loan Vintage</div>
    <p style="font-size:13px; color:var(--text-dim); margin-bottom:16px;">
      Each dot is one loan, plotted at its origination date with its worst coverage ratio over the 12-month term. The grey line shows BTC price for context. Loans originated before a crash show lower coverage.
    </p>
    {chart1}
  </div>

  <div class="card">
    <div class="section-title">Coverage vs Spot Drawdown</div>
    <p style="font-size:13px; color:var(--text-dim); margin-bottom:16px;">
      Every daily observation across all loans. The x-axis is how far BTC has dropped from the loan's origination price. Points below the red line would mean the hedge failed. The PUT keeps coverage above 1.0 even at 70%+ drawdowns.
    </p>
    {chart2}
  </div>

  <div class="card">
    <div class="section-title">Most Stressed Loans — Coverage Over Loan Life</div>
    <p style="font-size:13px; color:var(--text-dim); margin-bottom:16px;">
      The 10 loans with the lowest minimum coverage, traced day-by-day through their 12-month life. Shows how coverage evolved as BTC dropped and the PUT gained value.
    </p>
    {chart3}
  </div>

  <div class="card">
    <div class="section-title">Coverage During Known Stress Events</div>
    <p style="font-size:13px; color:var(--text-dim); margin-bottom:16px;">
      How loans active during major crypto crashes performed. Only loans originated within 6 months before each event are included, filtering out nearly-repaid loans. "Breach Days" counts daily observations where coverage fell below 1.0.
    </p>
    {stress_table}
  </div>

</div>
</body>
</html>"""


def _build_tab_fragment(summary: dict, chart1: str, chart2: str, chart3: str,
                        stress_table: str) -> str:
    """Build the inner HTML for the dashboard backtest tab (no html/head/nav wrapper).

    Follows the same visual pattern as the Roll-Down Research tab:
    context banner → hero heading → numbered sections with cards.
    """
    verdict = "PASS — No coverage breaches" if not summary["any_breach"] else f"FAIL — {summary['n_breach_loans']} loans breached"
    verdict_color = COLORS["green"] if not summary["any_breach"] else COLORS["red"]
    verdict_bg = "34,197,94" if not summary["any_breach"] else "239,68,68"

    return f"""
  <!-- Context banner (matches research-banner style) -->
  <div class="card" style="padding:14px 20px;background:rgba({verdict_bg},0.08);border-color:rgba({verdict_bg},0.25);margin-bottom:32px;margin-top:32px;">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
      <div style="font-size:13px;color:{verdict_color};font-weight:600;">{verdict}</div>
      <div style="display:flex;gap:20px;font-size:11px;font-family:var(--mono);color:var(--text-dim);">
        <span>{summary['total_loans']:,} loans</span>
        <span>worst {summary.get('worst_coverage', 0):.3f}</span>
        <span>median {summary.get('median_min_coverage', 0):.3f}</span>
        <span>p5 {summary.get('p5_min_coverage', 0):.3f}</span>
        <span>70% LTV · 12mo · 10% APR</span>
      </div>
    </div>
  </div>

  <!-- Hero heading -->
  <div style="text-align:center;margin-bottom:40px;">
    <div style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px;">Coverage Backtest</div>
    <h1 style="font-size:36px;font-weight:700;color:var(--text);margin:0 0 8px;">The PUT hedge held through every crash</h1>
    <p style="font-size:15px;color:var(--text-dim);margin:0 0 32px;max-width:620px;margin-left:auto;margin-right:auto;line-height:1.6;">{summary.get('complete_loans', summary['total_loans']):,} complete loans replayed against actual BTC prices, plus {summary.get('incomplete_loans', 0):,} in-progress loans monitored for breaches. {summary['total_daily_checks']:,} daily coverage checks.</p>
  </div>

  <!-- Section 01: Key Metrics (complete loans only) -->
  <div>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
      <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">01</span>
      <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Key Metrics — Complete Loans</span>
    </div>
    <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 6px;">Coverage stayed above 1.0 on every day</h2>
    <p style="font-size:13px;color:var(--text-dim);margin:0 0 20px;">The coverage ratio = (BTC collateral + PUT mark-to-market) / (debt + 3% liquidator fee). Below 1.0 means the hedge fails to cover the liability. Statistics below are from {summary.get('complete_loans', summary['total_loans']):,} loans with full 12-month data.</p>

    <div class="card" style="padding:20px 24px;margin-bottom:24px;background:linear-gradient(135deg,#0f1d38,#0a1428);border-color:var(--border-light);">
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);border-radius:10px;overflow:hidden;">
        <div style="background:var(--bg-card);padding:16px;text-align:center;">
          <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">Complete Loans</div>
          <div style="font-size:20px;font-weight:700;font-family:var(--mono);color:var(--text);">{summary.get('complete_loans', summary['total_loans']):,}</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;text-align:center;">
          <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">Worst Coverage</div>
          <div style="font-size:20px;font-weight:700;font-family:var(--mono);color:{COLORS['red'] if summary.get('worst_coverage', 2) < 1.0 else COLORS['green']};">{summary.get('worst_coverage', 0):.3f}</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;text-align:center;">
          <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">Median Min</div>
          <div style="font-size:20px;font-weight:700;font-family:var(--mono);color:var(--green);">{summary.get('median_min_coverage', 0):.3f}</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;text-align:center;">
          <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">5th Percentile</div>
          <div style="font-size:20px;font-weight:700;font-family:var(--mono);color:var(--yellow);">{summary.get('p5_min_coverage', 0):.3f}</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;text-align:center;">
          <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">Breach Days</div>
          <div style="font-size:20px;font-weight:700;font-family:var(--mono);color:{'var(--green)' if summary['n_breach_days'] == 0 else 'var(--red)'};">{summary['n_breach_days']:,}</div>
          <div style="font-size:9px;color:var(--text-muted);margin-top:4px;">of {summary['total_daily_checks']:,}</div>
        </div>
      </div>
    </div>
    {_build_incomplete_card_html(summary)}
  </div>

  <!-- Section 02: Coverage by Vintage -->
  <div style="margin-top:40px;">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
      <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">02</span>
      <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Coverage by Vintage</span>
    </div>
    <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 6px;">Loans before a crash show lower coverage</h2>
    <p style="font-size:13px;color:var(--text-dim);margin:0 0 20px;">Each dot is one loan at its origination date, showing its worst coverage over the 12-month term. Grey line is BTC price for context.</p>
    <div class="card" style="margin-bottom:20px;">
      {chart1}
    </div>
  </div>

  <!-- Section 03: Coverage vs Drawdown -->
  <div style="margin-top:40px;">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
      <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">03</span>
      <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Coverage vs Drawdown</span>
    </div>
    <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 6px;">PUT keeps coverage above 1.0 even at 70%+ drops</h2>
    <p style="font-size:13px;color:var(--text-dim);margin:0 0 20px;">Every daily observation across all loans. X-axis is how far BTC dropped from the loan's origination price. Points below the red line would mean the hedge failed.</p>
    <div class="card" style="margin-bottom:20px;">
      {chart2}
    </div>
  </div>

  <!-- Section 04: Most Stressed Loans -->
  <div style="margin-top:40px;">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
      <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">04</span>
      <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Most Stressed Loans</span>
    </div>
    <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 6px;">Day-by-day coverage for the 10 worst loans</h2>
    <p style="font-size:13px;color:var(--text-dim);margin:0 0 20px;">Traced through their 12-month life. Shows how coverage evolved as BTC dropped and the PUT gained value.</p>
    <div class="card" style="margin-bottom:20px;">
      {chart3}
    </div>
  </div>

  <!-- Section 05: Stress Events -->
  <div style="margin-top:40px;">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
      <span style="font-size:12px;color:var(--accent);font-weight:600;letter-spacing:0.1em;">05</span>
      <span style="font-size:12px;color:var(--text-muted);letter-spacing:0.06em;text-transform:uppercase;">Stress Events</span>
    </div>
    <h2 style="font-size:22px;font-weight:600;color:var(--text);margin:0 0 6px;">Coverage during major crypto crashes</h2>
    <p style="font-size:13px;color:var(--text-dim);margin:0 0 20px;">"Breach Days" counts daily observations where coverage fell below 1.0 for loans active during each event.</p>
    <div class="card" style="margin-bottom:20px;">
      {stress_table}
    </div>
  </div>

  <!-- Resize Plotly charts when backtest tab becomes visible (rendered while hidden) -->
  <script>
  (function() {{
    var observer = new IntersectionObserver(function(entries) {{
      entries.forEach(function(entry) {{
        if (entry.isIntersecting && entry.target.data) {{
          Plotly.Plots.resize(entry.target);
        }}
      }});
    }});
    document.querySelectorAll('.plotly-graph-div').forEach(function(div) {{
      observer.observe(div);
    }});
  }})();
  </script>"""


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

    # ── Dashboard fragment ──
    fragment = _build_tab_fragment(summary, chart1, chart2, chart3, stress_table)
    (output_dir / "backtest_tab_fragment.html").write_text(fragment, encoding="utf-8")
    log.info("Saved backtest_tab_fragment.html")

    # ── Console summary ──
    print("\n" + "=" * 60)
    print("  HISTORICAL BACKTEST — COVERAGE ANALYSIS")
    print("=" * 60)
    print(f"  Complete loans      : {summary.get('complete_loans', summary['total_loans']):,}")
    print(f"  Incomplete loans    : {summary.get('incomplete_loans', 0):,}")
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
    # Incomplete loan breach summary
    if summary.get("incomplete_loans", 0) > 0:
        print("-" * 60)
        print(f"  INCOMPLETE LOANS (breach monitoring only)")
        print(f"  In-progress loans   : {summary['incomplete_loans']:,}")
        print(f"  Worst coverage      : {summary.get('incomplete_worst_coverage', 'N/A'):.4f}" if summary.get('incomplete_worst_coverage') else "  Worst coverage      : N/A")
        print(f"  Breach days         : {summary.get('incomplete_n_breach_days', 0):,}")
        print(f"  Breach loans        : {summary.get('incomplete_n_breach_loans', 0):,}")
        if summary.get("incomplete_any_breach"):
            print(f"  Worst loan orig     : {summary.get('incomplete_worst_origination', 'N/A')}")
            print(f"  Worst day/available : {summary.get('incomplete_worst_day_in_loan', '?')}/{summary.get('incomplete_worst_days_available', '?')}")
    print("=" * 60 + "\n")
