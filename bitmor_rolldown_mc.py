#!/usr/bin/env python3
"""
Bitmor PUT Roll-Down Cost Reduction Simulator.

Three-tier analysis:
  Tier 1: Pure historical backtest
  Tier 2: Recent loans with simulated GBM tails
  Tier 3: Forward MC from today's price
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from liquidation_utils import (
    bs_price,
    build_amortisation_schedule,
    calibrate_hist_mu_sigma,
    load_price,
    load_surface,
)
from rolldown_utils import (
    RegimeIndex,
    apply_slippage,
    generate_gbm_path,
    lookup_iv,
    map_tenor_bucket,
    nearest_price,
    snap_to_strike,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class LoanResult:
    start_date: pd.Timestamp
    spot_at_start: float
    initial_premium: float
    roll_profits: list[float]
    total_roll_profit: float
    terminal_payoff_static: float
    terminal_payoff_rolling: float
    static_net_cost: float
    rolling_net_cost: float
    net_savings: float           # roll_profits only (insurance cost reduction)
    savings_pct: float
    terminal_delta: float        # terminal_rolling - terminal_static (always <= 0)
    full_economic_delta: float   # roll_profits + terminal_delta (can be negative)
    num_rolls: float             # float to support averaged results
    final_spot: float
    debt_at_expiry: float
    total_slippage_cost: float = 0.0  # cumulative slippage across all rolls
    month_details: list[dict] = field(default_factory=list)


def simulate_single_loan(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    start_date: pd.Timestamp,
    ltv: float = 0.70,
    loan_tenor_months: int = 12,
    loan_rate: float = 0.10,
    payments_per_year: int = 12,
    min_roll_profit: float = 20.0,
    r: float = 0.0,
    regime_index: RegimeIndex | None = None,
) -> LoanResult:
    """Simulate one loan with static-vs-rolling PUT comparison.

    Args:
        daily_prices: Daily BTC prices (real, or real+GBM extension).
        surface: IV surface DataFrame (multi-index: date, ttm_days, mny).
            For future dates, the latest available snapshot is used
            (frozen-surface approach).
        start_date: Loan origination date.
    """
    # -- Month 0: Origination --
    s0 = nearest_price(daily_prices, start_date)
    d0 = ltv * s0
    amort = build_amortisation_schedule(d0, loan_rate, 1, payments_per_year)

    # Snap initial strike to exchange-listed grid
    K_initial = snap_to_strike(d0, s0)

    iv0 = lookup_iv(surface, start_date, 365, K_initial / s0)
    initial_premium = bs_price(s0, K_initial, 1.0, r, iv0, call=False)

    K_held = K_initial
    held_expiry_date = start_date + pd.Timedelta(days=365)
    K_static = K_initial
    roll_profits: list[float] = []
    month_details: list[dict] = []
    total_slippage = 0.0

    # -- Months 1-11: Evaluate rolls --
    for month in range(1, loan_tenor_months):
        current_date = start_date + pd.DateOffset(months=month)
        st = nearest_price(daily_prices, current_date)
        dt = amort[month]
        remaining_months = loan_tenor_months - month

        tenor_days = map_tenor_bucket(remaining_months)

        # Snap replacement strike to exchange-listed grid
        K_replacement = snap_to_strike(dt, st)

        # -- Held PUT remaining TTM --
        held_days_left = max((held_expiry_date - current_date).days, 1)

        # -- IV lookup: use regime-matched surface date when available --
        surface_date = (regime_index.resolve(daily_prices, current_date)
                        if regime_index else current_date)
        iv_held = lookup_iv(surface, surface_date, held_days_left, K_held / st)
        iv_repl = lookup_iv(surface, surface_date, tenor_days, K_replacement / st)

        # Price held PUT (held_days_left already computed above)
        held_value_raw = bs_price(st, K_held, held_days_left / 365.0, r,
                                  iv_held, call=False)

        # Price replacement PUT
        replacement_tenor = tenor_days / 365.0
        replacement_cost_raw = bs_price(st, K_replacement, replacement_tenor,
                                        r, iv_repl, call=False)

        # Apply slippage: selling held put (bid side) and buying replacement (ask side)
        slip_sell = apply_slippage(held_value_raw, K_held / st)
        slip_buy = apply_slippage(replacement_cost_raw, K_replacement / st)
        held_value = held_value_raw - slip_sell
        replacement_cost = replacement_cost_raw + slip_buy

        profit = held_value - replacement_cost
        rolled = profit >= min_roll_profit

        month_details.append({
            "month": month,
            "date": str(current_date.date()),
            "surface_date": str(surface_date.date()),
            "spot": round(st, 2),
            "debt": round(dt, 2),
            "K_held": round(K_held, 2),
            "K_replacement": round(K_replacement, 2),
            "held_value_raw": round(held_value_raw, 2),
            "held_value": round(held_value, 2),
            "replacement_cost_raw": round(replacement_cost_raw, 2),
            "replacement_cost": round(replacement_cost, 2),
            "slippage_sell": round(slip_sell, 2),
            "slippage_buy": round(slip_buy, 2),
            "roll_profit": round(profit, 2),
            "rolled": rolled,
        })

        if rolled:
            roll_profits.append(profit)
            total_slippage += slip_sell + slip_buy
            K_held = K_replacement
            held_expiry_date = current_date + pd.Timedelta(days=tenor_days)

    # -- Month 12: Expiration --
    final_date = start_date + pd.DateOffset(months=loan_tenor_months)
    s_final = nearest_price(daily_prices, final_date)

    tp_static = max(K_static - s_final, 0.0)
    tp_rolling = max(K_held - s_final, 0.0)
    total_rp = sum(roll_profits)
    d_final = amort[-1]  # debt at expiry (near 0 for fully amortized)

    static_net = initial_premium - tp_static
    rolling_net = initial_premium - total_rp - tp_rolling

    # Net savings = roll profits captured (insurance cost reduction).
    # The terminal payoff difference is tracked separately as terminal_delta
    # because payoff above outstanding debt is a windfall, not a hedging cost.
    savings = total_rp
    savings_pct = (savings / initial_premium * 100) if initial_premium > 0 else 0.0
    t_delta = tp_rolling - tp_static  # always <= 0
    full_econ = total_rp + t_delta    # can be negative (risk disclosure metric)

    return LoanResult(
        start_date=start_date,
        spot_at_start=s0,
        initial_premium=initial_premium,
        roll_profits=roll_profits,
        total_roll_profit=total_rp,
        terminal_payoff_static=tp_static,
        terminal_payoff_rolling=tp_rolling,
        static_net_cost=static_net,
        rolling_net_cost=rolling_net,
        net_savings=savings,
        savings_pct=savings_pct,
        terminal_delta=t_delta,
        full_economic_delta=full_econ,
        num_rolls=len(roll_profits),
        final_spot=s_final,
        debt_at_expiry=d_final,
        total_slippage_cost=total_slippage,
        month_details=month_details,
    )


def run_tier1(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    backtest_years: int = 3,
    start_freq: str = "daily",
    **loan_kwargs,
) -> list[LoanResult]:
    """Tier 1: Pure historical backtest — every start date uses 100% real data."""
    last_date = daily_prices.index[-1]
    tier1_end = last_date - pd.DateOffset(years=1)
    tier1_start = last_date - pd.DateOffset(years=1 + backtest_years)

    freq_map = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}
    start_dates = pd.date_range(tier1_start, tier1_end,
                                freq=freq_map.get(start_freq, "D"))
    start_dates = start_dates[start_dates >= daily_prices.index[0]]

    # Tier 1: all months are historical — no RV-based lookup needed
    results: list[LoanResult] = []
    for sd in start_dates:
        try:
            results.append(simulate_single_loan(daily_prices, surface, sd,
                                                **loan_kwargs))
        except (ValueError, KeyError) as e:
            logging.warning("Tier 1 skipping %s: %s", sd.date(), e)

    logging.info("Tier 1: %d loans evaluated", len(results))
    return results


def _average_month_details(results: list[LoanResult]) -> list[dict]:
    """Average per-month roll details across MC paths.

    Groups by month number and averages numeric fields (spot, debt, K_held,
    K_replacement, roll_profit).  ``rolled`` is set to 1 if the majority of
    paths rolled in that month.
    """
    from collections import defaultdict
    buckets: dict[int, list[dict]] = defaultdict(list)
    for r in results:
        for md in r.month_details:
            buckets[md["month"]].append(md)
    if not buckets:
        return []
    avg_details = []
    for month in sorted(buckets):
        entries = buckets[month]
        k = len(entries)
        avg_details.append({
            "month": month,
            "spot": sum(e["spot"] for e in entries) / k,
            "debt": sum(e["debt"] for e in entries) / k,
            "K_held": sum(e["K_held"] for e in entries) / k,
            "K_replacement": sum(e["K_replacement"] for e in entries) / k,
            "roll_profit": sum(e["roll_profit"] for e in entries) / k,
            "rolled": sum(1 for e in entries if e["rolled"]) > k / 2,
        })
    return avg_details


def average_results(results: list[LoanResult]) -> LoanResult:
    """Average numeric fields across MC path results for one start date."""
    n = len(results)
    return LoanResult(
        start_date=results[0].start_date,
        spot_at_start=results[0].spot_at_start,
        initial_premium=results[0].initial_premium,
        roll_profits=[],
        total_roll_profit=sum(r.total_roll_profit for r in results) / n,
        terminal_payoff_static=sum(r.terminal_payoff_static for r in results) / n,
        terminal_payoff_rolling=sum(r.terminal_payoff_rolling for r in results) / n,
        static_net_cost=sum(r.static_net_cost for r in results) / n,
        rolling_net_cost=sum(r.rolling_net_cost for r in results) / n,
        net_savings=sum(r.net_savings for r in results) / n,
        savings_pct=sum(r.savings_pct for r in results) / n,
        terminal_delta=sum(r.terminal_delta for r in results) / n,
        full_economic_delta=sum(r.full_economic_delta for r in results) / n,
        num_rolls=sum(r.num_rolls for r in results) / n,
        final_spot=sum(r.final_spot for r in results) / n,
        debt_at_expiry=sum(r.debt_at_expiry for r in results) / n,
        total_slippage_cost=sum(r.total_slippage_cost for r in results) / n,
        month_details=_average_month_details(results),
    )


def run_tier2(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    n_mc_paths: int = 1000,
    start_freq: str = "daily",
    mu: float = 0.0,
    sigma: float = 0.5,
    seed: int | None = None,
    regime_index: RegimeIndex | None = None,
    **loan_kwargs,
) -> list[LoanResult]:
    """Tier 2: Recent loans — real data up to today, GBM tails for remaining months.

    When regime_index is provided, forward months use conditional surface
    matching instead of the frozen latest snapshot.
    """
    last_date = daily_prices.index[-1]
    tier2_start = last_date - pd.DateOffset(years=1)

    freq_map = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}
    start_dates = pd.date_range(tier2_start, last_date,
                                freq=freq_map.get(start_freq, "D"))
    start_dates = start_dates[start_dates >= daily_prices.index[0]]

    rng = np.random.default_rng(seed)
    loan_tenor = loan_kwargs.get("loan_tenor_months", 12)

    results: list[LoanResult] = []
    for sd in start_dates:
        end_needed = sd + pd.DateOffset(months=loan_tenor)
        path_results: list[LoanResult] = []

        for _ in range(n_mc_paths):
            if end_needed > last_date:
                days_forward = (end_needed - last_date).days + 30
                spot_at_cutoff = float(daily_prices.iloc[-1])
                gbm = generate_gbm_path(spot_at_cutoff, mu, sigma,
                                        days_forward, rng)
                gbm_dates = pd.date_range(last_date + pd.Timedelta(days=1),
                                          periods=days_forward, freq="D")
                extended = pd.concat([
                    daily_prices,
                    pd.Series(gbm[1:], index=gbm_dates, name="close"),
                ])
            else:
                extended = daily_prices

            try:
                path_results.append(
                    simulate_single_loan(extended, surface, sd,
                                         regime_index=regime_index,
                                         **loan_kwargs))
            except (ValueError, KeyError):
                continue

        if path_results:
            results.append(average_results(path_results))

    logging.info("Tier 2: %d start dates evaluated (%d paths each)",
                 len(results), n_mc_paths)
    return results


def run_tier3(
    daily_prices: pd.Series,
    surface: pd.DataFrame,
    n_forward_paths: int = 1000,
    mu: float = 0.0,
    sigma: float = 0.5,
    seed: int | None = None,
    regime_index: RegimeIndex | None = None,
    **loan_kwargs,
) -> list[LoanResult]:
    """Tier 3: Forward MC — full GBM paths from today's spot price.

    When regime_index is provided, each month's IV lookup uses a historical
    surface date matched by trailing return, instead of the frozen snapshot.
    """
    last_date = daily_prices.index[-1]
    spot_today = float(daily_prices.iloc[-1])
    loan_tenor = loan_kwargs.get("loan_tenor_months", 12)

    rng = np.random.default_rng(seed)
    n_days = loan_tenor * 31 + 30  # enough days to cover loan

    # Prepend real history so 7-day lookback works for early simulated months
    history_tail = daily_prices[last_date - pd.Timedelta(days=10):]

    results: list[LoanResult] = []
    for _ in range(n_forward_paths):
        gbm = generate_gbm_path(spot_today, mu, sigma, n_days, rng)
        gbm_dates = pd.date_range(last_date, periods=n_days + 1, freq="D")
        gbm_series = pd.Series(gbm, index=gbm_dates, name="close")

        # Concatenate real tail (excluding last_date to avoid duplicate)
        # with the full GBM path starting at last_date
        path_prices = pd.concat([history_tail.iloc[:-1], gbm_series])

        try:
            results.append(
                simulate_single_loan(path_prices, surface, last_date,
                                     regime_index=regime_index,
                                     **loan_kwargs))
        except (ValueError, KeyError) as e:
            logging.warning("Tier 3 path skipped: %s", e)

    logging.info("Tier 3: %d forward paths evaluated", len(results))
    return results


import argparse
import datetime as dt


def format_tier_report(results: list[LoanResult], title: str) -> str:
    """Format tier results into a printable report string."""
    if not results:
        return f"\n=== {title}: No results ==="

    n = len(results)
    avg = lambda attr: sum(getattr(r, attr) for r in results) / n
    savings_list = sorted(r.net_savings for r in results)
    dates = [r.start_date for r in results]
    date_range = (f"{min(dates).strftime('%Y-%m-%d')} to "
                  f"{max(dates).strftime('%Y-%m-%d')}")

    avg_prem = avg("initial_premium")
    avg_sav = avg("net_savings")
    avg_pct = (avg_sav / avg_prem * 100) if avg_prem > 0 else 0

    avg_econ = avg("full_economic_delta")
    avg_econ_pct = (avg_econ / avg_prem * 100) if avg_prem > 0 else 0

    lines = [
        f"\n=== {title} ({n} loans, {date_range}) ===",
        f"  Avg initial PUT premium        : ${avg_prem:,.2f}",
        f"  Avg roll savings (cost reduct.): ${avg_sav:,.2f} ({avg_pct:.1f}% of premium)",
        f"  Median roll savings            : ${savings_list[n // 2]:,.2f}",
        f"  Range                          : ${savings_list[0]:,.2f} to ${savings_list[-1]:,.2f}",
        f"  Avg rolls per loan             : {avg('num_rolls'):.1f}",
        f"  % loans where rolling helped   : {sum(1 for r in results if r.net_savings > 0) / n * 100:.1f}%",
        f"  ---",
        f"  Avg terminal payoff (static)   : ${avg('terminal_payoff_static'):,.2f}",
        f"  Avg terminal payoff (rolling)  : ${avg('terminal_payoff_rolling'):,.2f}",
        f"  Avg terminal delta             : ${avg('terminal_delta'):,.2f}",
        f"  Avg full economic delta        : ${avg_econ:,.2f} ({avg_econ_pct:.1f}% of premium)",
        f"  Avg total slippage cost        : ${avg('total_slippage_cost'):,.2f}",
    ]
    return "\n".join(lines)


def format_tier3_report(results: list[LoanResult], spot_today: float) -> str:
    """Format Tier 3 report with percentiles."""
    base = format_tier_report(results, f"Tier 3: Forward MC from Today "
                              f"({len(results)} paths, spot = ${spot_today:,.2f})")
    if not results:
        return base

    savings = [r.net_savings for r in results]
    pcts = np.percentile(savings, [5, 25, 50, 75, 95])
    base += (f"\n  Percentiles (5/25/50/75/95)    : "
             f"${pcts[0]:,.2f} / ${pcts[1]:,.2f} / ${pcts[2]:,.2f} / "
             f"${pcts[3]:,.2f} / ${pcts[4]:,.2f}")
    return base


def save_tier_csv(results: list[LoanResult], filepath: str) -> None:
    """Save per-loan/per-path results to CSV."""
    rows = []
    for idx, r in enumerate(results):
        rows.append({
            "path_id": idx,
            "start_date": r.start_date.strftime("%Y-%m-%d"),
            "spot": round(r.spot_at_start, 2),
            "initial_premium": round(r.initial_premium, 2),
            "roll_savings": round(r.net_savings, 2),
            "roll_savings_pct": round(r.savings_pct, 2),
            "effective_put_cost_pct": round(r.initial_premium / r.spot_at_start * 100, 2),
            "rolling_net_cost_pct": round((r.initial_premium - r.net_savings) / r.spot_at_start * 100, 2),
            "terminal_payoff_static": round(r.terminal_payoff_static, 2),
            "terminal_payoff_rolling": round(r.terminal_payoff_rolling, 2),
            "terminal_delta": round(r.terminal_delta, 2),
            "full_economic_delta": round(r.full_economic_delta, 2),
            "total_slippage_cost": round(r.total_slippage_cost, 2),
            "num_rolls": (int(r.num_rolls) if r.num_rolls == int(r.num_rolls)
                          else round(r.num_rolls, 1)),
            "final_spot": round(r.final_spot, 2),
            "debt_at_expiry": round(r.debt_at_expiry, 2),
        })
    pd.DataFrame(rows).to_csv(filepath, index=False)
    logging.info("Saved %d rows to %s", len(rows), filepath)


def save_detail_csv(results: list[LoanResult], filepath: str) -> None:
    """Save per-month roll details to CSV. Skips results with empty month_details."""
    columns = ["path_id", "month", "spot", "debt",
               "K_held", "K_replacement", "roll_profit", "rolled"]
    rows = []
    for idx, r in enumerate(results):
        for md in r.month_details:
            rows.append({
                "path_id": idx,
                "month": md["month"],
                "spot": round(md["spot"], 2),
                "debt": round(md["debt"], 2),
                "K_held": round(md["K_held"], 2),
                "K_replacement": round(md["K_replacement"], 2),
                "roll_profit": round(md["roll_profit"], 2),
                "rolled": int(md["rolled"]),
            })
    pd.DataFrame(rows, columns=columns).to_csv(filepath, index=False)
    logging.info("Saved %d detail rows to %s", len(rows), filepath)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bitmor PUT Roll-Down Cost Reduction Simulator")
    p.add_argument("--surface", default="btc_iv_surface_svi.csv",
                   help="Path to SVI IV surface CSV")
    p.add_argument("--price", default="BTCUSDT_1h.csv",
                   help="Path to hourly BTC price CSV")
    p.add_argument("--ltv", type=float, default=0.70)
    p.add_argument("--loan_tenor_months", type=int, default=12)
    p.add_argument("--loan_rate", type=float, default=0.10)
    p.add_argument("--payments_per_year", type=int, default=12)
    p.add_argument("--min_roll_profit", type=float, default=20.0)
    p.add_argument("--r", type=float, default=0.0, help="Risk-free rate")
    p.add_argument("--backtest_years", type=int, default=5)
    p.add_argument("--start_freq", default="daily",
                   choices=["daily", "weekly", "monthly"])
    p.add_argument("--n_mc_paths", type=int, default=100,
                   help="MC paths per start date (Tier 2)")
    p.add_argument("--n_forward_paths", type=int, default=1000,
                   help="Full forward MC paths (Tier 3)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--no-regime-match", action="store_true",
                   help="Disable conditional surface matching for Tier 2/3 "
                        "(use frozen surface instead)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    surface = load_surface(args.surface)
    price_hourly = load_price(args.price)
    daily_prices = price_hourly.resample("1D").last().dropna()

    mu, sigma = calibrate_hist_mu_sigma(price_hourly)
    logging.info("Calibrated GBM: mu=%.4f, sigma=%.4f", mu, sigma)

    regime_index = (None if args.no_regime_match
                    else RegimeIndex(daily_prices, surface))
    if regime_index:
        logging.info("Regime matching enabled (7-day trailing return)")

    loan_kwargs = dict(
        ltv=args.ltv,
        loan_tenor_months=args.loan_tenor_months,
        loan_rate=args.loan_rate,
        payments_per_year=args.payments_per_year,
        min_roll_profit=args.min_roll_profit,
        r=args.r,
    )

    today = dt.date.today().strftime("%Y%m%d")

    # -- Tier 1 (all historical) --
    tier1 = run_tier1(daily_prices, surface, args.backtest_years,
                      args.start_freq, **loan_kwargs)
    print(format_tier_report(tier1, "Tier 1: Pure Historical"))
    save_tier_csv(tier1, f"result/rolldown_tier1_{today}.csv")
    save_detail_csv(tier1, f"result/rolldown_tier1_detail_{today}.csv")

    # -- Tier 2 (real data up to today, GBM tails) --
    tier2 = run_tier2(daily_prices, surface, args.n_mc_paths, args.start_freq,
                      mu, sigma, args.seed, regime_index=regime_index,
                      **loan_kwargs)
    print(format_tier_report(tier2, "Tier 2: Recent + Simulated"))
    save_tier_csv(tier2, f"result/rolldown_tier2_{today}.csv")
    save_detail_csv(tier2, f"result/rolldown_tier2_detail_{today}.csv")

    # -- Tier 3 (full GBM) --
    spot_today = float(daily_prices.iloc[-1])
    tier3 = run_tier3(daily_prices, surface, args.n_forward_paths,
                      mu, sigma, args.seed, regime_index=regime_index,
                      **loan_kwargs)
    print(format_tier3_report(tier3, spot_today))
    save_tier_csv(tier3, f"result/rolldown_tier3_{today}.csv")
    save_detail_csv(tier3, f"result/rolldown_tier3_detail_{today}.csv")

    # -- Embed results into dashboard and open it --
    import subprocess
    dashboard = "bitmor-dashboard.html"
    logging.info("Embedding CSV data into %s ...", dashboard)
    subprocess.run(
        [sys.executable, "embed_csv_to_dashboard.py", "--date", today,
         "--dashboard", dashboard],
        check=True,
    )

    import webbrowser
    import os
    path = os.path.abspath(dashboard)
    logging.info("Opening dashboard: %s", path)
    webbrowser.open(f"file://{path}")


if __name__ == "__main__":
    main()
