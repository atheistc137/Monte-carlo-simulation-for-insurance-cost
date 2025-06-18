#!/usr/bin/env python3
"""
liquidation_insurance_mc.py  —  Monte-Carlo quote for BTC liquidation
insurance.
(v 3.21, 2025-06-16)

Changes in v 3.21
─────────────────
• **Debug table** – when run with `--debug`, the script now prints a
  month-by-month table of every hedge roll with all key figures.
• Tape rows now include the option **pay-off**.
• Version bump to 3.21.
"""

from __future__ import annotations

import argparse
import logging
import math
from datetime import date
from pathlib import Path
from typing import List, Tuple, Union

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from scipy.stats import norm

###############################################################################
#                               Black–Scholes                                #
###############################################################################


def bs_price(S: float, K: float, T: float, r: float, sigma: float,
             call: bool = True) -> float:
    """Black-Scholes price for a European call/put."""
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


###############################################################################
#                           CSV loaders (TZ-naïve)                           #
###############################################################################


def load_surface(path: Path) -> pd.DataFrame:
    surf = (pd.read_csv(path, parse_dates=["date"])               # type: ignore[arg-type]
              .set_index(["date", "ttm_days", "mny"]).sort_index())
    # force tz-naïve index levels
    surf.index = surf.index.set_levels(surf.index.levels[0].tz_localize(None),
                                       level=0)
    surf.index = surf.index.set_levels(surf.index.levels[1].astype(int), level=1)
    return surf


def load_price(path: Path) -> pd.Series:
    px = pd.read_csv(path, parse_dates=[0])                        # type: ignore[arg-type]
    px.columns = ["timestamp", "close"][:len(px.columns)]
    px["timestamp"] = pd.to_datetime(px["timestamp"]).dt.tz_localize(None)
    return px.set_index("timestamp")["close"].sort_index()


###############################################################################
#                    Weekly realised-vol → IV lookup table                   #
###############################################################################


def build_weekly_iv_table(surface: pd.DataFrame,
                          price: pd.Series,
                          tenor_days: int = 30,
                          window_days: int = 7) -> pd.DataFrame:
    logging.info("Building weekly IV lookup for %d-day tenor …", tenor_days)
    px_daily = price.resample("1D").last().dropna()
    log_ret = np.log(px_daily / px_daily.shift(1))
    ann = math.sqrt(365 / window_days)
    roll_sig = (log_ret.rolling(window_days).std() * ann).dropna()

    tenor = int(tenor_days)
    if tenor not in surface.index.levels[1]:
        raise ValueError(f"Surface lacks {tenor}-day tenor")
    tenor_slice = surface.xs(tenor, level="ttm_days", drop_level=False)
    surf_dates = tenor_slice.index.levels[0]

    rows: list[tuple[pd.Timestamp, float, float, float]] = []
    for week_end, rv in roll_sig.resample("W").last().dropna().items():
        if (cands := surf_dates[surf_dates <= week_end]).empty:
            continue
        surf_date = cands.max()
        slice_ = tenor_slice.loc[surf_date]

        for idx, iv in slice_["iv"].items():
            mny = float(idx[-1]) if isinstance(idx, tuple) else float(idx)
            iv_dec = iv * 0.01 if iv > 1 else float(iv)
            rows.append((surf_date, rv, mny, iv_dec))

    tbl = (pd.DataFrame(rows, columns=["week_end", "real_vol", "mny", "iv"])
             .sort_values("week_end").reset_index(drop=True))
    if tbl.empty:
        raise RuntimeError("Weekly IV lookup table came out empty")
    logging.info("Weekly IV table built (%d rows)", len(tbl))
    return tbl


def lookup_iv_weekly(tbl: pd.DataFrame, rv_sim: float, mny: float) -> float:
    """Pick the IV row with closest moneyness then closest realised-vol."""
    if not np.isfinite(rv_sim):
        raise ValueError("Simulated realised-vol is NaN")
    subset = tbl.iloc[np.abs(tbl["mny"] - mny).argsort()[:10]]
    subset = subset.iloc[np.abs(subset["real_vol"] - rv_sim).argsort()]
    iv = float(subset.iloc[0]["iv"])
    if iv <= 0:
        raise ValueError("Non-positive IV")
    return iv


###############################################################################
#                        Historic μ and σ (hourly px)                        #
###############################################################################


def calibrate_hist_mu_sigma(px: pd.Series,
                            annualisation: int = 365 * 24) -> Tuple[float, float]:
    log_ret = np.log(px / px.shift(1)).dropna()
    mu = log_ret.mean() * annualisation
    sigma = log_ret.std() * math.sqrt(annualisation)
    return mu, sigma


###############################################################################
#                       Amortisation schedule helper                         #
###############################################################################


def build_amortisation_schedule(principal: float, annual_rate: float,
                                years: int, payments_per_year: int = 12) -> List[float]:
    """Return the outstanding *principal* before each payment.

    The list length is *years × payments_per_year + 1* – item 0 is the initial
    principal.  Item i (1-based) is the balance *after* the i-th payment (and
    thus the amount that has to be insured for the following month).
    """
    if principal <= 0:
        raise ValueError("Principal must be positive")
    if years <= 0 or payments_per_year <= 0:
        raise ValueError("years and payments_per_year must be positive")

    rate_per_period = annual_rate / payments_per_year
    n_periods = years * payments_per_year
    payment = (principal * rate_per_period) / (1 - (1 + rate_per_period) ** -n_periods)

    balances = [principal]
    bal = principal
    for _ in range(n_periods):
        interest = bal * rate_per_period
        principal_repay = payment - interest
        bal = max(0.0, bal - principal_repay)  # avoid negative due to rounding
        balances.append(bal)
    return balances  # length n_periods + 1


###############################################################################
#                            One-path MC engine                              #
###############################################################################


def simulate_one_path(
    rng: np.random.Generator,
    weekly_tbl: pd.DataFrame,
    spot0: float,
    mu: float,
    sigma_hist: float,
    years: int,
    hedge_interval_days: int,
    hedge_ratio: float,
    r: float = 0.0,
    debug: bool = False,
    principal_sched: List[float] | None = None,
) -> Union[
    Tuple[float, float, float, float, float, float, List[dict]],
    Tuple[float, float, float, float, float, float,
          List[float], List[float], List[float]]
]:
    """Run a single Monte-Carlo path.

    If *principal_sched* is supplied, the hedge strike follows that schedule
    (rounded up to the next $1 000).  Otherwise the legacy fixed-strike
    behaviour *(K = spot0 × hedge_ratio)* is used.
    """
    import itertools  # local import to keep global namespace clean

    total_days = years * 365
    dt = 1 / 365

    # ── Strike initialisation ───────────────────────────────────────────
    if principal_sched is None:
        K_prev = spot0 * hedge_ratio
        sched = itertools.repeat(None)  # type: ignore[assignment]
    else:
        sched = [math.ceil(x / 1000.0) * 1000.0 for x in principal_sched]
        K_prev = sched[0]
        sched_idx = 0  # points *to* the option currently held

    iv0 = lookup_iv_weekly(weekly_tbl, sigma_hist, K_prev / spot0)
    prem_prev = bs_price(spot0, K_prev, hedge_interval_days / 365, r, iv0,
                         call=False)

    cum_pnl = 0.0
    monthly_caps: List[float] = [prem_prev]  # month-0 capital
    max_monthly_cap = prem_prev

    min_price = max_price = spot0

    tape: List[dict] = [] if debug else None
    if debug:
        tape.append({"step": 0, "t_years": 0.0, "trade_date": str(date.today()),
                     "spot": spot0, "strike": K_prev, "iv": iv0,
                     "premium": prem_prev, "payoff": 0.0,
                     "pnl": 0.0, "cum_pnl": 0.0,
                     "capital_req": prem_prev})

    spot = spot0
    last_7 = [spot0] * 7  # sliding window for realised-vol proxy
    annual_days = [365 * i for i in range(1, years + 1)]
    yearly_pnls = [0.0] * years
    prev_cum = 0.0

    for day in range(1, total_days + 1):
        # simulate spot for the day (GBM)
        spot = max(1e-8,
                   spot * math.exp((mu - 0.5 * sigma_hist ** 2) * dt +
                                   sigma_hist * rng.standard_normal() * math.sqrt(dt)))
        min_price = min(min_price, spot)
        max_price = max(max_price, spot)
        last_7.pop(0)
        last_7.append(spot)

        # roll year-to-date P&L into yearly bucket
        if day in annual_days:
            idx = annual_days.index(day)
            yearly_pnls[idx] = cum_pnl - prev_cum
            prev_cum = cum_pnl

        # hedge only at the specified interval
        if day % hedge_interval_days:
            continue

        # ── Pay-off from the option that just expired ────────────────
        payoff = max(K_prev - spot, 0.0)
        pnl = payoff - prem_prev
        cum_pnl += pnl

        # ── Decide if we still need protection for next month ────────
        if principal_sched is None:
            K_next_rounded = K_prev  # fixed-strike mode
        else:
            if sched_idx >= len(sched) - 1:  # loan fully repaid ⇒ no new hedge
                monthly_caps.append(0.0)
                max_monthly_cap = max(max_monthly_cap, 0.0)
                prem_prev = 0.0
                if debug:
                    tape.append({"step": len(tape), "t_years": day / 365,
                                 "trade_date": str(date.today() + relativedelta(days=day)),
                                 "spot": spot, "strike": 0.0, "iv": 0.0,
                                 "premium": 0.0, "payoff": payoff,
                                 "pnl": pnl, "cum_pnl": cum_pnl,
                                 "capital_req": 0.0})
                continue  # simulation keeps running, but no further hedging

            # outstanding principal *after* the upcoming payment
            sched_idx += 1
            K_next_rounded = sched[sched_idx]

        # if the next strike is zero, there’s nothing to insure any more
        if K_next_rounded <= 0.0:
            monthly_caps.append(0.0)
            max_monthly_cap = max(max_monthly_cap, 0.0)
            prem_prev = 0.0
            K_prev = 0.0
            if debug:
                tape.append({"step": len(tape), "t_years": day / 365,
                             "trade_date": str(date.today() + relativedelta(days=day)),
                             "spot": spot, "strike": 0.0, "iv": 0.0,
                             "premium": 0.0, "payoff": payoff,
                             "pnl": pnl, "cum_pnl": cum_pnl,
                             "capital_req": 0.0})
            continue

        # ── Price the new option (Black-Scholes) ─────────────────────
        rv_sim = (np.std(np.diff(np.log(last_7))) * math.sqrt(365 / (len(last_7) - 1))
                  if len(set(last_7)) > 1 else 0.0)
        iv = lookup_iv_weekly(weekly_tbl, rv_sim, K_next_rounded / spot)
        prem = bs_price(spot, K_next_rounded, hedge_interval_days / 365, r, iv,
                        call=False)

        cap_req = max(0.0, prem - payoff)
        monthly_caps.append(cap_req)
        max_monthly_cap = max(max_monthly_cap, cap_req)

        # ── Housekeeping for next loop ───────────────────────────────
        if debug:
            tape.append({"step": len(tape), "t_years": day / 365,
                         "trade_date": str(date.today() + relativedelta(days=day)),
                         "spot": spot, "strike": K_next_rounded, "iv": iv,
                         "premium": prem, "payoff": payoff,
                         "pnl": pnl, "cum_pnl": cum_pnl,
                         "capital_req": cap_req})

        prem_prev = prem
        K_prev = K_next_rounded

    # ── Aggregate statistics for the path ────────────────────────────────
    avg_monthly_cap = float(np.mean(monthly_caps))
    final_price = spot

    if debug:
        return (cum_pnl, max_monthly_cap, avg_monthly_cap,
                final_price, min_price, max_price, tape)

    months_logged = len(monthly_caps) - 1   # exclude month-0
    mpy = months_logged // years if months_logged else 0           # should be 12
    caps_mat = np.array(monthly_caps[1:1 + years * mpy]).reshape(years, mpy) if mpy else np.zeros((years, 1))

    yearly_avg_monthly_caps = caps_mat.mean(axis=1).tolist()
    yearly_max_monthly_caps = caps_mat.max(axis=1).tolist()

    return (cum_pnl, max_monthly_cap, avg_monthly_cap,
            final_price, min_price, max_price,
            yearly_pnls, yearly_avg_monthly_caps, yearly_max_monthly_caps)


###############################################################################
#                                CLI / main                                  #
###############################################################################


def parse_args():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--surface", required=True, help="SVI surface CSV")
    p.add_argument("--price", required=True, help="Spot price CSV")

    p.add_argument("--years", type=int, default=5, help="Horizon (years)")
    p.add_argument("--n_paths", type=int, default=50000, help="Monte-Carlo runs")
    p.add_argument("--hedge_ratio", type=float, default=0.8,
                   help="Initial strike / spot ratio (legacy mode)")
    p.add_argument("--steps_per_year", type=int, default=12,
                   help="Re-hedge frequency (per year)")
    p.add_argument("--s0", type=float, default=100_000, help="Initial BTC spot (USD)")
    p.add_argument("--rate", type=float, default=0.0, help="Risk-free rate (r)")

    # ── new in v3.20 ─────────────────────────────────────────────────────
    p.add_argument("--loan_rate", type=float, default=0.10,
                   help="Annual loan interest rate (e.g. 0.10 = 10 %)")
    p.add_argument("--principal", type=float, default=None,
                   help="Loan principal.  Defaults to s0 × hedge_ratio if omitted.")

    p.add_argument("--debug", action="store_true", help="Run a single path verbosely")
    p.add_argument("--seed", type=int, default=None, help="Random seed")
    return p.parse_args()


def main() -> None:
    cfg = parse_args()
    logging.basicConfig(format="%(asctime)s  %(levelname)s  %(message)s",
                        level=logging.INFO)

    surface = load_surface(Path(cfg.surface))
    price = load_price(Path(cfg.price))

    mu, sigma_hist = calibrate_hist_mu_sigma(price)
    logging.info("Annualised μ = %.3f   σ = %.3f", mu, sigma_hist)

    hedge_days = 365 // cfg.steps_per_year
    weekly_tbl = build_weekly_iv_table(surface, price, tenor_days=hedge_days)

    rng = np.random.default_rng(cfg.seed)

    # ── amortisation schedule (if principal given / implied) ─────────────
    principal = (cfg.principal if cfg.principal is not None
                 else cfg.s0 * cfg.hedge_ratio)
    amort_sched = build_amortisation_schedule(principal, cfg.loan_rate,
                                              cfg.years, cfg.steps_per_year)

    # ── debug single path ────────────────────────────────────────────────
    if cfg.debug:
        (pnl, cap, avg_cap, sp_f, mn_p, mx_p, tape) = simulate_one_path(
            rng, weekly_tbl, cfg.s0, mu, sigma_hist,
            cfg.years, hedge_days, cfg.hedge_ratio, cfg.rate, True,
            principal_sched=amort_sched)

        print("\n── DEBUG SUMMARY ───────────────────────────────────────────")
        print(f"Total {cfg.years}-yr P&L                   : {pnl:,.2f}")
        print(f"Max monthly capital                        : {cap:,.2f}")
        print(f"Average monthly capital                    : {avg_cap:,.2f}")
        print(f"Final / min / max BTC price                : "
              f"{sp_f:,.2f} / {mn_p:,.2f} / {mx_p:,.2f}")

        # ── month-by-month tape ────────────────────────────────────────
        df_tape = pd.DataFrame(tape)
        pd.set_option("display.max_rows", None)
        pd.set_option("display.width", None)

        fmt = {
            'spot': '{:,.2f}'.format,
            'strike': '{:,.2f}'.format,
            'iv': '{:.4f}'.format,
            'premium': '{:,.2f}'.format,
            'payoff': '{:,.2f}'.format,
            'pnl': '{:,.2f}'.format,
            'cum_pnl': '{:,.2f}'.format,
            'capital_req': '{:,.2f}'.format,
        }

        print("\n── MONTH-BY-MONTH HEDGE PATH ───────────────────────────────")
        print(df_tape.to_string(index=False, formatters=fmt))
        return

    # ── multi-path Monte-Carlo ───────────────────────────────────────────
    n, years = cfg.n_paths, cfg.years
    net_pnls = np.empty(n)
    max_caps = np.empty(n)
    avg_monthly_caps = np.empty(n)
    final_prices = np.empty(n)
    min_prices = np.empty(n)
    max_prices = np.empty(n)

    yearly_pnls_arr = np.empty((n, years))
    yearly_avg_caps_arr = np.empty((n, years))
    yearly_max_caps_arr = np.empty((n, years))

    for i in range(n):
        (pnl, mcap, amcap, fpx, mnpx, mxpx,
         ypnls, yavgc, ymaxc) = simulate_one_path(
            rng, weekly_tbl, cfg.s0, mu, sigma_hist,
            years, hedge_days, cfg.hedge_ratio, cfg.rate, False,
            principal_sched=amort_sched)

        net_pnls[i] = pnl
        max_caps[i] = mcap
        avg_monthly_caps[i] = amcap
        final_prices[i] = fpx
        min_prices[i] = mnpx
        max_prices[i] = mxpx

        yearly_pnls_arr[i] = ypnls
        yearly_avg_caps_arr[i] = yavgc
        yearly_max_caps_arr[i] = ymaxc

    # ── Summary metrics ──────────────────────────────────────────────────
    total_pnl = net_pnls.sum()
    mean_total_net_pnl = net_pnls.mean()
    loss_95, loss_99 = np.percentile(net_pnls, [5, 1])
    months = years * 12
    avg_monthly_pnl = mean_total_net_pnl / months
    sum_max_caps = max_caps.sum()

    avg_pnl_years = yearly_pnls_arr.mean(axis=0)
    avg_month_cap_years = yearly_avg_caps_arr.mean(axis=0)
    mean_max_cap_years = yearly_max_caps_arr.mean(axis=0)

    print(f"\nMonte-Carlo results  ({n:,} paths, {years} years):")
    print(f"  Total net P&L across all paths        : {total_pnl:,.2f}")
    print(f"  Mean total net P&L per path           : {mean_total_net_pnl:,.2f}")
    print(f"  95th / 99th % gains                  : "
          f"{np.percentile(net_pnls, 95):,.2f} / {np.percentile(net_pnls, 99):,.2f}")
    print(f"  95th / 99th % losses                 : {loss_95:,.2f} / {loss_99:,.2f}")
    print(f"  Average monthly P&L                   : {avg_monthly_pnl:,.2f}")
    print(f"  Sum of max monthly capital (all sims) : {sum_max_caps:,.2f}")
    print(f"  Avg final / min / max BTC price       : "
          f"{final_prices.mean():,.2f} / {min_prices.mean():,.2f} / {max_prices.mean():,.2f}\n")

    for yr in range(1, years + 1):
        print(f"  Year {yr}:  avg P&L = {avg_pnl_years[yr - 1]:,.2f}   | "
              f"avg monthly cap = {avg_month_cap_years[yr - 1]:,.2f}   | "
              f"mean max cap = {mean_max_cap_years[yr - 1]:,.2f}")

    # ── Write one-row summary CSV ───────────────────────────────────────
    today_str = date.today().strftime("%Y%m%d")
    out_dir = Path("result")
    out_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "total_net_pnl": total_pnl,
        "mean_total_net_pnl": mean_total_net_pnl,
        "pct95_gain": np.percentile(net_pnls, 95),
        "pct99_gain": np.percentile(net_pnls, 99),
        "pct5_loss": loss_95,
        "pct1_loss": loss_99,
        "avg_monthly_pnl": avg_monthly_pnl,
        "sum_max_month_cap": sum_max_caps,
        "avg_final_price": final_prices.mean(),
        "avg_low_price": min_prices.mean(),
        "avg_high_price": max_prices.mean(),
    }
    for yr in range(1, years + 1):
        record[f"avg_pnl_year_{yr}"] = avg_pnl_years[yr - 1]
        record[f"avg_monthly_cap_year_{yr}"] = avg_month_cap_years[yr - 1]
        record[f"mean_max_cap_year_{yr}"] = mean_max_cap_years[yr - 1]

    pd.DataFrame([record]).to_csv(out_dir / f"summary_{today_str}.csv", index=False)
    print(f"\nSummary saved to  result/summary_{today_str}.csv")


if __name__ == "__main__":
    main()
