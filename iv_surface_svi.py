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
DEFAULT_MAX_FF_DAYS = 60

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


# ────────────────────────── CLI ───────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opt", default="btc_iv_surface2.csv",  help="Input: options CSV file")
    p.add_argument("--px", default="BTCUSDT_1h.csv",  help="Input: spot CSV file")
    p.add_argument("--out_param", default="btc_svi_params.csv",   help="Output: SVI parameters per day")
    p.add_argument("--out_surf",  default="btc_iv_surface_svi.csv", help="Output: synthetic IV surface grid")
    p.add_argument("--min_quotes", type=int, default=DEFAULT_MIN_QUOTES, help="Minimum quotes per day")
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

    pd.DataFrame(surf_rows).to_csv(cfg.out_surf, index=False, float_format="%.6f")
    logging.info("Saved synthetic IV grid → %s (%d rows)", cfg.out_surf, len(surf_rows))


if __name__ == "__main__":
    main()
