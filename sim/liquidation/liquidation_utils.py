#!/usr/bin/env python3
"""
Utility helpers for liquidation_insurance_mc.py
Only stateless, reusable functions live here.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm


# ───────────────────────────── Black–Scholes ────────────────────────────────
def bs_price(S: float, K: float, T: float, r: float, sigma: float,
             call: bool = True) -> float:
    """Black-Scholes price for a European option."""
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# ───────────────────────────── CSV loaders ──────────────────────────────────
def load_surface(path: Path) -> pd.DataFrame:
    surf = (pd.read_csv(path, parse_dates=["date"])
              .set_index(["date", "ttm_days", "mny"])
              .sort_index())
    surf.index = surf.index.set_levels(surf.index.levels[0].tz_localize(None), level=0)
    surf.index = surf.index.set_levels(surf.index.levels[1].astype(int), level=1)
    return surf


def load_price(path: Path) -> pd.Series:
    px = pd.read_csv(path, parse_dates=[0])
    if len(px.columns) == 2:
        px.columns = ["timestamp", "close"]
    else:
        # OHLCV format: find close column by name, use first col as timestamp
        close_col = [c for c in px.columns if "close" in c.lower()][0]
        px = px[[px.columns[0], close_col]]
        px.columns = ["timestamp", "close"]
    px["timestamp"] = pd.to_datetime(px["timestamp"]).dt.tz_localize(None)
    return px.set_index("timestamp")["close"].sort_index()


# ─────────────────── Weekly RV → IV lookup construction ────────────────────
def build_weekly_iv_table(surface: pd.DataFrame,
                          price: pd.Series,
                          tenor_days: int = 30,
                          window_days: int = 7) -> pd.DataFrame:
    logging.info("Building weekly IV lookup for %d-day tenor …", tenor_days)

    px_daily = price.resample("1D").last().dropna()
    log_ret  = np.log(px_daily / px_daily.shift(1))
    ann      = math.sqrt(365 / window_days)
    roll_sig = (log_ret.rolling(window_days).std() * ann).dropna()

    tenor = int(tenor_days)
    if tenor not in surface.index.levels[1]:
        raise ValueError(f"Surface lacks {tenor}-day tenor")

    tenor_slice = surface.xs(tenor, level="ttm_days", drop_level=False)
    surf_dates  = tenor_slice.index.get_level_values("date").unique()

    rows: list[tuple[pd.Timestamp, float, float, float]] = []
    for week_end, rv in roll_sig.resample("W").last().dropna().items():
        if (cands := surf_dates[surf_dates <= week_end]).empty:
            continue
        surf_date = cands.max()
        slice_    = tenor_slice.loc[surf_date]

        for idx, iv in slice_["iv"].items():
            mny     = float(idx[-1]) if isinstance(idx, tuple) else float(idx)
            iv_dec  = iv * 0.01 if iv > 1 else float(iv)
            rows.append((surf_date, rv, mny, iv_dec))

    tbl = (pd.DataFrame(rows, columns=["week_end", "real_vol", "mny", "iv"])
             .sort_values("week_end")
             .reset_index(drop=True))
    if tbl.empty:
        raise RuntimeError("Weekly IV lookup table came out empty")

    logging.info("Weekly IV table built (%d rows)", len(tbl))
    return tbl


def lookup_iv_weekly(tbl: pd.DataFrame, rv_sim: float, mny: float) -> float:
    """Nearest-neighbour IV lookup (first on moneyness, then on realised-vol)."""
    if not np.isfinite(rv_sim):
        raise ValueError("Simulated realised-vol is NaN")

    subset = tbl.iloc[np.abs(tbl["mny"] - mny).argsort()[:10]]
    subset = subset.iloc[np.abs(subset["real_vol"] - rv_sim).argsort()]
    iv     = float(subset.iloc[0]["iv"])
    if iv <= 0:
        raise ValueError("Non-positive IV")
    return iv


# ─────────────────────── Historic μ and σ calibrator ───────────────────────
def calibrate_hist_mu_sigma(px: pd.Series,
                            annualisation: int = 365,
                            window_years: int = 3) -> Tuple[float, float]:
    daily = px.resample("1D").last().dropna()
    if window_years:
        cutoff = daily.index[-1] - pd.DateOffset(years=window_years)
        daily = daily[daily.index >= cutoff]
    log_ret = np.log(daily / daily.shift(1)).dropna()
    mu      = log_ret.mean() * annualisation
    sigma   = log_ret.std()  * math.sqrt(annualisation)
    return mu, sigma


# ───────────────────── Amortisation schedule helper ────────────────────────
def build_amortisation_schedule(principal: float, annual_rate: float, years: int,
                                payments_per_year: int = 12,
                                accrual_rate: float | None = None) -> List[float]:
    """Build a loan amortisation schedule, returning outstanding balances.

    Parameters
    ----------
    principal : float
        Initial loan amount.
    annual_rate : float
        Rate used to SIZE the fixed monthly payment (billing ceiling).
        When *accrual_rate* is ``None`` this is also the interest accrual rate.
    years : int
        Loan term in years.
    payments_per_year : int
        Number of payments per year (default 12 = monthly).
    accrual_rate : float | None
        Annual rate at which interest actually accrues.  When ``None``,
        defaults to *annual_rate* (single-rate, backward-compatible).
        Typically lower than *annual_rate* (e.g. 0.10 vs 0.15).

    Returns
    -------
    List[float]
        Outstanding balance after each period, length ``n_periods + 1``.
        ``balances[0] == principal``, ``balances[-1] == 0.0``.
    """
    if principal <= 0:
        raise ValueError("Principal must be positive")
    if years <= 0 or payments_per_year <= 0:
        raise ValueError("years and payments_per_year must be positive")

    sizing_rpp = annual_rate / payments_per_year
    n_periods  = years * payments_per_year
    payment    = (principal * sizing_rpp) / (
                    1 - (1 + sizing_rpp) ** -n_periods)

    accrual_rpp = (accrual_rate / payments_per_year
                   if accrual_rate is not None
                   else sizing_rpp)

    balances = [principal]
    bal      = principal
    for i in range(n_periods):
        interest = bal * accrual_rpp
        if i < n_periods - 1:
            principal_repay = min(payment - interest, bal)
            bal = max(0.0, bal - principal_repay)
        else:
            bal = 0.0
        balances.append(bal)

    return balances
