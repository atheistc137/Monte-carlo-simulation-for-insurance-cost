"""
Utility helpers for the Bitmor PUT roll-down simulator.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from liquidation_utils import bs_price, build_weekly_iv_table

# Mapping from option tenor (months) to calendar days
TENOR_DAYS: dict[int, int] = {3: 90, 6: 180, 9: 270, 12: 365}


def map_tenor_bucket(remaining_months: int,
                     available_tenors: list[int] | None = None) -> int:
    """Map remaining loan months to the smallest available tenor bucket (in days).

    Rule: pick the smallest available tenor >= remaining_months.
    Fallback: longest available tenor.
    """
    if available_tenors is None:
        available_tenors = [3, 6, 9, 12]
    for t in sorted(available_tenors):
        if t >= remaining_months:
            return TENOR_DAYS[t]
    return TENOR_DAYS[max(available_tenors)]


def map_tenor_bucket_days(days: int, available_tenors_days: list[int]) -> int:
    """Map a day count to the nearest available IV table tenor (in days).

    Rule: smallest available tenor >= days. Fallback: longest available.
    """
    for t in sorted(available_tenors_days):
        if t >= days:
            return t
    return max(available_tenors_days)


class _SurfaceCache:
    """Pre-indexes a surface DataFrame for fast repeated lookups.

    Stores IV grids as numpy arrays keyed by (date, ttm_days) for O(1)
    dict lookups + vectorised nearest-moneyness search.
    """

    def __init__(self, surface: pd.DataFrame):
        dates = surface.index.get_level_values("date").unique().sort_values()
        self.dates_arr = dates.values.astype("datetime64[ns]")

        # Build (date_idx, ttm) → (mny_arr, iv_arr) lookup
        self._grid: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        self._ttm_vals: dict[int, np.ndarray] = {}  # date_idx → ttm array

        for i, d in enumerate(dates):
            day = surface.loc[d]
            ttm_vals = day.index.get_level_values("ttm_days").unique().values.astype(int)
            self._ttm_vals[i] = np.sort(ttm_vals)
            for t in ttm_vals:
                ts = day.loc[t]
                mny_arr = ts.index.get_level_values("mny").values.astype(float)
                iv_arr = ts["iv"].values.astype(float)
                self._grid[(i, int(t))] = (mny_arr, iv_arr)

    def lookup(self, date: pd.Timestamp, ttm_days: int, moneyness: float) -> float:
        dt64 = np.datetime64(date, "ns")
        idx = int(self.dates_arr.searchsorted(dt64, side="right")) - 1
        if idx < 0:
            raise ValueError(f"No surface data on or before {date}")

        ttm_vals = self._ttm_vals[idx]
        nearest_ttm = int(ttm_vals[np.abs(ttm_vals - ttm_days).argmin()])

        mny_arr, iv_arr = self._grid[(idx, nearest_ttm)]
        nearest_idx = int(np.abs(mny_arr - moneyness).argmin())

        return float(iv_arr[nearest_idx]) / 100.0


_surface_caches: dict[int, _SurfaceCache] = {}


def lookup_iv(surface: pd.DataFrame, date: pd.Timestamp,
              ttm_days: int, moneyness: float) -> float:
    """Look up IV from SVI surface by nearest (date <= query, ttm, moneyness).

    Returns IV as a decimal (e.g. 0.50 for 50%).
    Uses a pre-built cache for fast repeated lookups.
    """
    key = id(surface)
    if key not in _surface_caches:
        logging.info("Building surface lookup cache …")
        _surface_caches[key] = _SurfaceCache(surface)
    return _surface_caches[key].lookup(date, ttm_days, moneyness)


def nearest_price(daily_prices: pd.Series,
                  target_date: pd.Timestamp) -> float:
    """Get the price nearest to target_date from a daily price series."""
    idx = daily_prices.index.get_indexer([target_date], method="nearest")[0]
    if idx < 0:
        raise ValueError(f"No price data near {target_date}")
    return float(daily_prices.iloc[idx])


def generate_gbm_path(spot0: float, mu: float, sigma: float,
                      n_days: int, rng: np.random.Generator) -> np.ndarray:
    """Generate a daily GBM price path (vectorised).

    Returns array of length n_days + 1 (includes spot0 at index 0).
    """
    dt = 1.0 / 365
    z = rng.standard_normal(n_days)
    log_returns = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
    prices = np.empty(n_days + 1)
    prices[0] = spot0
    prices[1:] = spot0 * np.exp(np.cumsum(log_returns))
    return prices


def compute_rv_from_prices(daily_prices: pd.Series,
                           as_of_date: pd.Timestamp,
                           window_days: int = 7) -> float:
    """Annualised realized volatility from a trailing daily price window.

    Used during simulated months to drive the RV-based IV lookup.
    """
    window_start = as_of_date - pd.Timedelta(days=window_days + 2)
    window = daily_prices[window_start:as_of_date]
    if len(window) < 3:
        return 0.0
    log_ret = np.log(window / window.shift(1)).dropna()
    return float(log_ret.std() * np.sqrt(365 / window_days))


def build_iv_tables(surface: pd.DataFrame, price: pd.Series,
                    tenor_days_list: list[int]) -> dict[int, pd.DataFrame]:
    """Build weekly (RV, moneyness) -> IV lookup tables for each tenor bucket.

    Maps each requested tenor to the nearest available TTM in the surface,
    so the RV-IV correlation is captured even before the IV pipeline is
    extended to include quarterly tenors.
    """
    available_ttm = sorted(surface.index.get_level_values("ttm_days").unique())
    tables: dict[int, pd.DataFrame] = {}
    for td in tenor_days_list:
        nearest_ttm = int(min(available_ttm, key=lambda x: abs(x - td)))
        try:
            tables[td] = build_weekly_iv_table(surface, price, tenor_days=nearest_ttm)
        except (ValueError, RuntimeError) as e:
            logging.warning("Cannot build IV table for %d-day tenor "
                            "(nearest %d): %s", td, nearest_ttm, e)
    return tables


def evaluate_roll(spot: float, K_held: float,
                  held_time_remaining: float,
                  debt_outstanding: float,
                  replacement_tenor: float,
                  r: float,
                  iv_held: float, iv_replacement: float,
                  min_roll_profit: float = 200.0) -> tuple[float, bool]:
    """Evaluate whether a PUT roll is profitable.

    Returns (roll_profit, should_roll).
    """
    held_value = bs_price(spot, K_held, held_time_remaining, r, iv_held, call=False)
    replacement_cost = bs_price(spot, debt_outstanding, replacement_tenor, r,
                                iv_replacement, call=False)
    profit = held_value - replacement_cost
    return profit, bool(profit >= min_roll_profit)
