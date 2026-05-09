#!/usr/bin/env python3
"""
iv_surface_svi.py — BTC implied-volatility surface generator (v 2.2, 2025-06-09)
==================================================================================
Fully self-contained script that cleans mixed-layout option CSVs (now handles 8-column files),
calibrates a raw-SVI model in parallel for every trading day, and exports both the fitted
parameter history and a synthetic IV surface on a moneyness × maturity grid.
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.optimize import minimize

# ───────────────────────── configuration defaults ──────────────────────────
MNY_GRID = np.arange(0.4, 3.00, 0.1)
TTM_GRID = np.sort(np.concatenate([np.arange(15, 61), [90, 180, 270, 365]]))
DEFAULT_MIN_QUOTES = 6
DEFAULT_MIN_QUOTES_LONG = 12
DEFAULT_MAX_FF_DAYS = 60
LONG_TENOR_BUCKETS = {"180d", "270d", "365d"}
LONG_TTMS = [90, 180, 270, 365]

# ───────────────────────── tenor bucketing ────────────────────────────────
TENOR_BUCKETS = [
    ("short", 3,   60),
    ("90d",   61,  135),
    ("180d",  136, 225),
    ("270d",  226, 315),
    ("365d",  316, 400),
]


def assign_tenor_bucket(ttm_days: float) -> str:
    """Assign a TTM value to its tenor bucket label."""
    for label, lo, hi in TENOR_BUCKETS:
        if lo <= ttm_days <= hi:
            return label
    if ttm_days < 3:
        return "short"
    return "365d"


# ───────────────────────── regex helpers ────────────────────────────────────
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")     # yyyy-mm-dd
_INST_RX = re.compile(r"^BTC-[0-9A-Z]+-\d+-[CP]$")  # rough instrument pattern

# ───────────────────────── data loaders ─────────────────────────────────────
def load_options(path: Path) -> pd.DataFrame:
    """Load option quotes, fixing mixed layouts (now supports extra 'price' column) and dropping bad rows."""
    rows: List[List[str]] = []
    with path.open(newline="") as f:
        rdr = csv.reader(f)
        next(rdr, None)  # skip header
        for r in rdr:
            # require at least the 7 core fields
            if len(r) < 7:
                continue
            # dominant (shifted) layout: [date, expiry, inst, strike, type, ttm, iv, ...]
            if _DATE_RX.match(r[1]):
                date, expiry, inst, strike, otype, ttm, iv = r[:7]
                rows.append([date, inst, strike, otype, expiry, ttm, iv])
            # legacy layout (instrument in r[1]) – skip
            elif _INST_RX.match(r[1]):
                continue
            else:
                continue

    df = pd.DataFrame(
        rows,
        columns=["date", "instrument", "strike", "option_type", "expiry", "ttm_days", "iv"],
    )

    # dtype conversions
    df["date"]   = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.normalize()
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce", utc=True).dt.normalize()
    df[["strike", "ttm_days", "iv"]] = df[["strike", "ttm_days", "iv"]].apply(
        pd.to_numeric, errors="coerce"
    )
    # convert IV from percent (e.g. 30) to decimal (0.30)
    df["iv"] = df["iv"] / 100.0

    return df.dropna().query("iv > 1e-6")


def load_price(path: Path) -> pd.Series:
    px = pd.read_csv(path, parse_dates=[0], on_bad_lines="skip")
    px.columns = ["timestamp", "close"][: len(px.columns)]
    px["timestamp"] = pd.to_datetime(px["timestamp"], utc=True)
    daily = px.set_index("timestamp").sort_index()["close"].resample("1D").last().ffill()
    return daily


# ──────────────────────── SVI helpers ──────────────────────────────────────
def svi_total_variance(k: np.ndarray, a: float, b: float, rho: float, m: float, sigma: float) -> np.ndarray:
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma**2))


def calibrate_svi(
    k: np.ndarray, t: np.ndarray, iv: np.ndarray
) -> Tuple[float, float, float, float, float, float]:
    w_market = (iv ** 2) * t

    def obj(theta):
        a, b, rho, m, sigma = theta
        if b <= 0 or not -0.999 < rho < 0.999 or sigma <= 0:
            return 1e9
        return float(np.mean((svi_total_variance(k, a, b, rho, m, sigma) - w_market) ** 2))

    guess  = [1e-4, 0.1, -0.3, 0.0, 0.1]
    bounds = [(-1, 2), (1e-8, 5), (-0.999, 0.999), (-2, 2), (1e-6, 2)]
    res    = minimize(obj, guess, method="L-BFGS-B", bounds=bounds)
    a, b, rho, m, sigma = res.x
    return a, b, rho, m, sigma, res.fun


def calibrate_one_day(d: pd.Timestamp, tenor_bucket: str,
                      grp: pd.DataFrame) -> Dict[str, float] | None:
    if len(grp) < calibrate_one_day.min_quotes:
        logging.debug("%s/%s skipped (< %d quotes)", d.date(), tenor_bucket,
                      calibrate_one_day.min_quotes)
        return None
    k  = np.log(grp["strike"].values / grp["spot"].values)
    t  = grp["ttm_days"].values / 365.0
    iv = grp["iv"].values
    a, b, rho, m, sigma, err = calibrate_svi(k, t, iv)
    return {
        "date":         d,
        "tenor_bucket": tenor_bucket,
        "a":            a,
        "b":            b,
        "rho":          rho,
        "m":            m,
        "sigma":        sigma,
        "error":        err,
        "quotes":       len(grp),
    }


# ────────────────────────── data quality filters ─────────────────────────
def clean_svi_params(params: pd.DataFrame, min_quotes_short: int = DEFAULT_MIN_QUOTES,
                     min_quotes_long: int = DEFAULT_MIN_QUOTES_LONG) -> pd.DataFrame:
    """Remove degenerate SVI fits before forward-fill.

    Filters applied (in order):
      1. Sigma floor — fits with sigma < 0.01 produce exploding wings.
      2. Quote floor — long tenors (180d/270d/365d) need >= min_quotes_long
         quotes for a reliable 5-parameter fit.
      3. Spike detection — for each tenor bucket, rows where ``a`` or ``b``
         deviate > 3 std from a 7-day rolling median are dropped.

    Dropped rows become NaN gaps that the downstream forward-fill inherits
    from the last good calibration day.
    """
    n_before = len(params)

    # 1. Sigma floor — degenerate curvature
    mask_sigma = params["sigma"] >= 0.01

    # 2. Per-tenor quote minimum
    is_long = params["tenor_bucket"].isin(LONG_TENOR_BUCKETS)
    mask_quotes = (~is_long | (params["quotes"] >= min_quotes_long)) & \
                  (is_long | (params["quotes"] >= min_quotes_short))

    # 3. Spike detection on a, b per tenor bucket (7-day rolling median)
    mask_spike = pd.Series(True, index=params.index)
    for _tb, grp in params.groupby("tenor_bucket"):
        grp_sorted = grp.sort_values("date")
        for col in ["a", "b"]:
            rolling_med = grp_sorted[col].rolling(7, center=True, min_periods=3).median()
            rolling_std = grp_sorted[col].rolling(7, center=True, min_periods=3).std()
            deviation = (grp_sorted[col] - rolling_med).abs()
            is_spike = deviation > 3 * rolling_std.clip(lower=1e-6)
            mask_spike.loc[grp_sorted.index[is_spike]] = False

    combined = mask_sigma & mask_quotes & mask_spike
    cleaned = params[combined].copy()
    n_dropped = n_before - len(cleaned)
    if n_dropped:
        logging.info("SVI quality filter: dropped %d / %d fits "
                     "(sigma: %d, quotes: %d, spikes: %d)",
                     n_dropped, n_before,
                     int((~mask_sigma).sum()),
                     int((~mask_quotes).sum()),
                     int((~mask_spike).sum()))
    return cleaned


def enforce_tv_monotonicity(surf_df: pd.DataFrame) -> pd.DataFrame:
    """Enforce total-variance monotonicity across long tenors.

    For each (date, moneyness) pair, total variance w = (IV/100)^2 * (T/365)
    must be non-decreasing as T increases.  If a shorter tenor has higher w
    than the next longer one, its IV is capped down — the shorter tenor is
    the suspect because adding calendar time should only add variance.
    """
    long_mask = surf_df["ttm_days"].isin(LONG_TTMS)
    if not long_mask.any():
        return surf_df

    surf_df = surf_df.copy()
    n_fixed = 0

    long_rows = surf_df[long_mask]
    for (_date, _mny), grp in long_rows.groupby(["date", "mny"]):
        if len(grp) < 2:
            continue
        idx = grp.sort_values("ttm_days").index
        ttms = surf_df.loc[idx, "ttm_days"].values.astype(float)
        ivs = surf_df.loc[idx, "iv"].values.copy()
        ws = (ivs / 100.0) ** 2 * (ttms / 365.0)

        # Walk backwards from longest tenor; cap shorter tenors down
        for i in range(len(ws) - 2, -1, -1):
            if ws[i] > ws[i + 1]:
                ws[i] = ws[i + 1]
                ivs[i] = np.sqrt(max(ws[i], 1e-12) / (ttms[i] / 365.0)) * 100.0
                n_fixed += 1

        surf_df.loc[idx, "iv"] = ivs

    if n_fixed:
        logging.info("Total-variance monotonicity: fixed %d points", n_fixed)
    return surf_df


# ────────────────────────── CLI ───────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opt", default="data/btc_iv_surface2.csv",  help="Input: options CSV file")
    p.add_argument("--px", default="data/BTCUSDT_1h.csv",  help="Input: spot CSV file")
    p.add_argument("--out_param", default="data/btc_svi_params.csv",   help="Output: SVI parameters per day")
    p.add_argument("--out_surf",  default="data/btc_iv_surface_svi.csv", help="Output: synthetic IV surface grid")
    p.add_argument("--min_quotes", type=int, default=DEFAULT_MIN_QUOTES, help="Minimum quotes per day (short tenors)")
    p.add_argument("--min_quotes_long", type=int, default=DEFAULT_MIN_QUOTES_LONG,
                   help="Minimum quotes for 180d/270d/365d tenors")
    p.add_argument("--max_ff_days", type=int, default=DEFAULT_MAX_FF_DAYS, help="Max forward-fill days for spot")
    p.add_argument("--n_jobs",    type=int, default=-1, help="Parallel jobs (-1 = all cores)")
    p.add_argument("--verbose",   action="store_true", help="Verbose logging")
    cfg = p.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.DEBUG if cfg.verbose else logging.INFO
    )

    logging.info("Loading option quotes from %s", cfg.opt)
    opt  = load_options(Path(cfg.opt))

    logging.info("Loading spot prices from %s", cfg.px)
    spot = load_price(Path(cfg.px))

    # Extend or trim spot to align with option date range
    max_opt_date = opt["date"].max()
    if max_opt_date > spot.index.max():
        extra = pd.date_range(
            spot.index.max() + pd.Timedelta(days=1),
            max_opt_date, freq="1D", tz="UTC"
        )
        if len(extra) > cfg.max_ff_days:
            logging.warning(
                "Option data exceed spot history by > %d days; trimming options.", 
                cfg.max_ff_days
            )
            opt = opt[opt["date"] <= spot.index.max()]
        else:
            spot = pd.concat([spot, pd.Series(spot.iloc[-1], index=extra)])

    # Merge datasets
    opt = opt.merge(spot.rename("spot"), left_on="date", right_index=True, how="inner")
    if opt.empty:
        raise RuntimeError("No overlapping dates between option data and spot prices.")

    # Assign tenor buckets
    opt["tenor_bucket"] = opt["ttm_days"].apply(assign_tenor_bucket)

    # Calibrate SVI per (date, tenor_bucket) in parallel
    calibrate_one_day.min_quotes = cfg.min_quotes
    results = Parallel(n_jobs=cfg.n_jobs)(
        delayed(calibrate_one_day)(d, tb, grp)
        for (d, tb), grp in opt.groupby(["date", "tenor_bucket"])
    )
    params = pd.DataFrame([r for r in results if r is not None])

    # ── Data quality filter ──────────────────────────────────────────
    if not params.empty:
        params = clean_svi_params(params,
                                  min_quotes_short=cfg.min_quotes,
                                  min_quotes_long=cfg.min_quotes_long)

    # Forward-fill sparse tenor buckets (with staleness cap)
    if not params.empty:
        params = params.sort_values(["tenor_bucket", "date"])
        filled_parts = []
        for tb, grp in params.groupby("tenor_bucket"):
            grp = grp.set_index("date").asfreq("D")
            grp["tenor_bucket"] = tb
            # Forward-fill SVI params, cap at max_ff_days
            svi_cols = ["a", "b", "rho", "m", "sigma", "error", "quotes"]
            grp[svi_cols] = grp[svi_cols].ffill(limit=cfg.max_ff_days)
            grp = grp.dropna(subset=["a"])  # drop rows beyond staleness cap
            filled_parts.append(grp.reset_index())
        params = pd.concat(filled_parts, ignore_index=True)

    Path(cfg.out_param).parent.mkdir(parents=True, exist_ok=True)
    params.to_csv(cfg.out_param, index=False)
    logging.info("Saved SVI parameters → %s (%d rows)", cfg.out_param, len(params))

    # Map tenor buckets to their TTM grid ranges
    BUCKET_TTM = {
        "short": [T for T in TTM_GRID if T <= 60],
        "90d":   [90],
        "180d":  [180],
        "270d":  [270],
        "365d":  [365],
    }

    # Build synthetic IV surface using per-bucket params
    surf_rows: List[Dict[str, float]] = []
    for _, row in params.iterrows():
        trade_date = row["date"]
        tb = row["tenor_bucket"]
        a, b, rho, m, sigma = row[["a", "b", "rho", "m", "sigma"]]
        try:
            spot_price = spot.loc[trade_date]
        except KeyError:
            continue
        for T in BUCKET_TTM.get(tb, []):
            t = T / 365.0
            for mny in MNY_GRID:
                K = mny * spot_price
                k = np.log(K / spot_price)
                w = svi_total_variance(k, a, b, rho, m, sigma)
                iv = np.sqrt(max(w, 1e-12) / t) * 100.0
                surf_rows.append(dict(date=trade_date, ttm_days=T, mny=mny, iv=iv))

    surf_df = pd.DataFrame(surf_rows)

    # ── Total-variance monotonicity across long tenors ───────────────
    if not surf_df.empty:
        surf_df = enforce_tv_monotonicity(surf_df)

    Path(cfg.out_surf).parent.mkdir(parents=True, exist_ok=True)
    surf_df.to_csv(cfg.out_surf, index=False, float_format="%.6f")
    logging.info("Saved synthetic IV grid → %s (%d rows)", cfg.out_surf, len(surf_df))


if __name__ == "__main__":
    main()
