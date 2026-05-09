"""
Historical backtest: replay every possible loan against actual prices + IV surface.

For each origination date in the backtest window:
  1. Originate loan at that day's spot price (same params as MC)
  2. Walk forward 360 days using actual historical prices
  3. Each day: compute debt from amortisation schedule, value PUT via BS with
     actual IV surface, compute coverage
  4. At monthly boundaries (day 30, 60, ...): attempt PUT rolldown
  5. Record daily coverage ratio

Loans where IV lookup fails at any point are skipped entirely (consistent
with the rolldown MC simulator which drops loans on IV gaps).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from sim.shared import config
from sim.liquidation.liquidation_waterfall import compute_waterfall
from sim.rolldown.rolldown_utils import lookup_iv, snap_to_strike, apply_slippage
from sim.liquidation.liquidation_utils import (
    bs_price, load_surface, load_price, build_amortisation_schedule,
)

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


def run_backtest(limit: int = 0) -> pd.DataFrame:
    """Run the full historical backtest. Returns DataFrame of daily coverage records."""

    # ── Load data ──
    log.info("Loading SVI surface from %s", config.SVI_SURFACE_CSV)
    surface = load_surface(config.SVI_SURFACE_CSV)

    log.info("Loading price data from %s", config.HOURLY_PRICE_CSV)
    price_hourly = load_price(config.HOURLY_PRICE_CSV)
    price_daily = price_hourly.resample("1D").last().dropna()

    # ── Determine backtest window ──
    # IV surface starts Apr 2021, prices go to Mar 2026
    # Complete loans need 360 days forward; incomplete loans run with whatever data is available
    surf_dates = surface.index.get_level_values("date").unique().sort_values()
    first_surface_date = pd.Timestamp(surf_dates[0])
    last_price_date = price_daily.index[-1]
    last_origination_full = last_price_date - pd.Timedelta(days=config.LOAN_TERM_MONTHS * config.DAYS_PER_MONTH)

    # Require at least 30 days of data for an incomplete loan to be useful
    min_incomplete_days = config.DAYS_PER_MONTH
    last_origination_any = last_price_date - pd.Timedelta(days=min_incomplete_days)

    # Origination dates: every day from first surface date to last usable origination
    all_dates = price_daily.loc[first_surface_date:last_origination_any].index

    if limit > 0:
        all_dates = all_dates[:limit]

    log.info("Backtest window: %s to %s (%d origination dates)",
             all_dates[0].strftime("%Y-%m-%d"),
             all_dates[-1].strftime("%Y-%m-%d"),
             len(all_dates))

    total_days = config.LOAN_TERM_MONTHS * config.DAYS_PER_MONTH  # 360
    monthly_rate = config.ACCRUAL_APR / 12

    records: List[dict] = []
    skipped = 0

    for loan_idx, orig_date in enumerate(all_dates):
        if loan_idx % max(1, len(all_dates) // 20) == 0:
            log.info("Loan %d / %d (originated %s)",
                     loan_idx, len(all_dates), orig_date.strftime("%Y-%m-%d"))

        spot_0 = float(price_daily.loc[orig_date])

        # ── Loan origination ──
        loan_amount = (1 - config.DEPOSIT_PCT / 100) * spot_0
        amort = build_amortisation_schedule(
            loan_amount, config.SIZING_APR, 1, 12,
            accrual_rate=config.ACCRUAL_APR)
        initial_put_strike = _snap_strike_up(
            spot_0 * (1 - config.DEPOSIT_PCT / 100) * (1 + config.STRIKE_BUFFER), spot_0)

        # Loan state
        allocated_btc = 1.0
        put_K = initial_put_strike
        initial_put_tenor_days = 365
        put_tenor_remaining = initial_put_tenor_days

        # How many days can this loan run? Full 360 or capped by available price data.
        available_days = min(total_days, (last_price_date - orig_date).days + 1)
        is_complete = available_days >= total_days

        loan_records: List[dict] = []
        try:
            for day in range(available_days):
                calendar_date = orig_date + pd.Timedelta(days=day)

                # Get actual price — use nearest available if exact date missing
                price_idx = price_daily.index.get_indexer([calendar_date], method="nearest")[0]
                spot_now = float(price_daily.iloc[price_idx])

                # ── Debt from amortisation schedule (monthly compounding) ──
                month = day // config.DAYS_PER_MONTH
                day_in_month = day % config.DAYS_PER_MONTH
                if month < len(amort) - 1:
                    # Accrue interest linearly within the month
                    debt = amort[month] * (1 + monthly_rate * day_in_month / config.DAYS_PER_MONTH)
                else:
                    debt = max(amort[-1], 0.0)

                # ── Monthly boundary: PUT rolldown ──
                if day > 0 and day % config.DAYS_PER_MONTH == 0:
                    remaining_months = config.LOAN_TERM_MONTHS - month

                    mny_held = put_K / spot_now
                    iv_held = lookup_iv(surface, calendar_date,
                                        max(put_tenor_remaining, 15), mny_held)

                    put_T = max(put_tenor_remaining / 365, 1 / 365)
                    held_put_value = bs_price(spot_now, put_K, put_T,
                                              config.RISK_FREE_RATE, iv_held, call=False)

                    new_raw_strike = debt * (1 + config.STRIKE_BUFFER) if debt > 0 else loan_amount * 0.5
                    new_K = _snap_strike_up(new_raw_strike, spot_now)
                    new_mny = new_K / spot_now
                    new_tenor_days = remaining_months * config.DAYS_PER_MONTH
                    new_tenor_T = max(new_tenor_days / 365, 1 / 365)

                    if new_tenor_days > 0:
                        iv_new = lookup_iv(surface, calendar_date,
                                           max(new_tenor_days, 15), new_mny)

                        replacement_cost = bs_price(spot_now, new_K, new_tenor_T,
                                                    config.RISK_FREE_RATE, iv_new, call=False)

                        slippage_sell = apply_slippage(held_put_value, mny_held)
                        slippage_buy = apply_slippage(replacement_cost, new_mny)
                        roll_profit = (held_put_value - slippage_sell) - (replacement_cost + slippage_buy)

                        if roll_profit >= config.MIN_ROLL_PROFIT:
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

                iv = lookup_iv(surface, calendar_date,
                               max(put_tenor_remaining, 15), mny)

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

                loan_records.append({
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
                    "loan_completed": is_complete,
                    "loan_days_available": available_days,
                })
        except (ValueError, KeyError) as e:
            skipped += 1
            log.debug("Skipping origination %s: %s",
                      orig_date.strftime("%Y-%m-%d"), e)
            continue

        records.extend(loan_records)

    n_complete = sum(1 for r in records if r.get("day_in_loan") == 0 and r.get("loan_completed"))
    n_incomplete = sum(1 for r in records if r.get("day_in_loan") == 0 and not r.get("loan_completed"))
    log.info("Backtest complete. %d daily records generated "
             "(%d complete loans, %d incomplete loans, %d skipped due to IV gaps).",
             len(records), n_complete, n_incomplete, skipped)
    return pd.DataFrame(records)
