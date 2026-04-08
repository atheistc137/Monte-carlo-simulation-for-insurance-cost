#!/usr/bin/env python3
"""
Monte‑Carlo quote for BTC liquidation‑insurance **with rational default**
Version 3.23  (2025‑07‑01)

Key additions vs 3.22
---------------------
* **Default logic** – each month, the borrower compares
  *the remaining scheduled payments* on the current loan with the *total
  payments* of a brand‑new loan sized `current_spot × hedge_ratio` (same
  rate, tenor). If restarting is cheaper, the current loan is closed and
  no further put protection is bought.
* **Simulation outputs** now include
  – `total_premium_cost` per path (sum of all put premiums actually paid)
  – `defaulted` flag and `default_month` (1‑based, 0 => no default)
* **Summary section** prints
  – % paths defaulted
  – average / max put spend **among defaulted paths**
  – average default month

All CLI options are unchanged.
"""
from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Tuple, Union, Dict, Any

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

# ─────────────────────────── local utilities ───────────────────────────────
from liquidation_utils import (                      # type: ignore
    bs_price,
    load_surface, load_price,
    build_weekly_iv_table, lookup_iv_weekly,
    calibrate_hist_mu_sigma,
    build_amortisation_schedule,
)

# ───────────────────────────── data classes ────────────────────────────────
@dataclass
class HedgeState:
    """Mutable state carried through one MC path."""
    spot:               float
    K_prev:             float
    prem_prev:          float
    cum_pnl:            float
    monthly_caps:       List[float]
    max_monthly_cap:    float
    min_price:          float
    max_price:          float
    last_7:             List[float]
    yearly_pnls:        List[float]
    prev_cum:           float
    sched_idx:          int = 0
    tape: List[Dict[str, Any]] | None = None

# ───────────────────────── helper functions ────────────────────────────────

def gbm_step(spot: float, mu: float, sigma: float, dt: float,
             rng: np.random.Generator) -> float:
    """One geometric‑Brownian step (daily)."""
    drift = (mu - 0.5 * sigma**2) * dt
    shock = sigma * math.sqrt(dt) * rng.standard_normal()
    return max(1e-6, spot * math.exp(drift + shock))


def realised_vol(last_7: List[float]) -> float:
    if len(set(last_7)) <= 1:
        return 0.0
    return np.std(np.diff(np.log(last_7))) * math.sqrt(365 / 6)


def payoff_and_pnl(spot: float, strike: float, prem_prev: float) -> Tuple[float, float]:
    payoff = max(strike - spot, 0.0)
    return payoff, payoff - prem_prev


def next_strike(principal_sched: List[float] | None, idx: int,
                hedge_ratio: float, spot0: float) -> Tuple[float, int]:
    """Return next strike ($1 000‑rounded) and updated amort‑index."""
    if principal_sched is None:
        return spot0 * hedge_ratio, idx
    if idx >= len(principal_sched) - 1:
        return 0.0, idx  # fully repaid
    idx += 1
    return math.ceil(principal_sched[idx] / 1_000) * 1_000.0, idx


def record_tape(state: HedgeState, step: int, t_years: float,
                iv: float, payoff: float, pnl: float, cap_req: float) -> None:
    if state.tape is None:
        return
    state.tape.append({
        "step": step,
        "t_years": t_years,
        "spot": state.spot,
        "strike": state.K_prev,
        "iv": iv,
        "premium": state.prem_prev,
        "payoff": payoff,
        "pnl": pnl,
        "cum_pnl": state.cum_pnl,
        "capital_req": cap_req,
    })

# ───────────────────────── one‑path simulation ─────────────────────────────

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
    loan_rate: float = 0.10,
    sizing_rate: float = 0.15,
    payments_per_year: int = 12,
) -> Union[
    Tuple[float, float, float, float, float, float, List[dict]],
    Tuple[float, float, float, float, float, float,
          List[float], List[float], List[float],
          float, bool, int]
]:
    """Simulate **one** Monte‑Carlo path.

    Returns (non‑debug):
        cum_pnl, max_monthly_cap, avg_monthly_cap,
        final_price, min_price, max_price,
        yearly_pnls, yearly_avg_caps, yearly_max_caps,
        total_premium_cost, defaulted?, default_month (1‑based, 0 if none)
    """

    # ── constants ──────────────────────────────────────────────────────
    dt                = 1/365
    total_days        = years * 365
    tape: List[dict] | None = [] if debug else None

    # amort & loan constants
    principal0        = (principal_sched[0] if principal_sched is not None
                         else spot0 * hedge_ratio)
    sizing_rpp        = sizing_rate / payments_per_year
    n_periods         = years * payments_per_year
    payment_orig      = (principal0 * sizing_rpp) / (1 - (1+sizing_rpp)**-n_periods)

    # ── initial option ────────────────────────────────────────────────
    K0         = math.ceil(principal0 / 1_000) * 1_000.0
    iv0        = lookup_iv_weekly(weekly_tbl, sigma_hist, K0/spot0)
    prem0      = bs_price(spot0, K0, hedge_interval_days/365, r, iv0, call=False)

    state = HedgeState(
        spot=spot0, K_prev=K0, prem_prev=prem0, cum_pnl=0.0,
        monthly_caps=[prem0], max_monthly_cap=prem0,
        min_price=spot0, max_price=spot0, last_7=[spot0]*7,
        yearly_pnls=[0.0]*years, prev_cum=0.0, tape=tape
    )

    if debug:
        record_tape(state, 0, 0.0, iv0, 0.0, 0.0, prem0)

    # trackers
    total_premium_cost = prem0
    defaulted          = False
    default_month      = 0

    annual_day_marks   = [365*i for i in range(1, years+1)]

    # ── daily loop ────────────────────────────────────────────────────
    for day in range(1, total_days+1):
        # 1️⃣  GBM price step
        state.spot = gbm_step(state.spot, mu, sigma_hist, dt, rng)
        state.min_price = min(state.min_price, state.spot)
        state.max_price = max(state.max_price, state.spot)
        state.last_7.pop(0); state.last_7.append(state.spot)

        # 2️⃣  yearly P&L bucket
        if day in annual_day_marks:
            i = annual_day_marks.index(day)
            state.yearly_pnls[i] = state.cum_pnl - state.prev_cum
            state.prev_cum = state.cum_pnl

        # 3️⃣  only hedge on roll days
        if day % hedge_interval_days:
            continue

        month_no = len(state.monthly_caps)  # 0‑based before append

        # ── option expiry ────────────────────────────────────────────
        payoff, pnl = payoff_and_pnl(state.spot, state.K_prev, state.prem_prev)
        state.cum_pnl += pnl

        # ── DEFAULT CHECK before new hedge ───────────────────────────
        if not defaulted:
            # remaining periods on *original* loan
            rem_periods = n_periods - month_no
            remaining_payments = max(0, rem_periods) * payment_orig

            # total payments on a fresh loan sized spot×hedge_ratio
            new_principal   = state.spot * hedge_ratio
            payment_new     = (new_principal * sizing_rpp) / (1 - (1+sizing_rpp)**-n_periods)
            total_new_cost  = payment_new * n_periods

            if total_new_cost < remaining_payments:
                defaulted = True
                default_month = month_no + 1  # convert to 1‑based when reporting
                # once defaulted, loan closed → no further options
                state.K_prev = 0.0
                state.prem_prev = 0.0

        # ── after default: record cap=0, skip new option --------------
        if defaulted:
            state.monthly_caps.append(0.0)
            record_tape(state, month_no+1, day/365, 0.0, payoff, pnl, 0.0)
            continue

        # ── determine next strike ------------------------------------
        K_next, state.sched_idx = next_strike(principal_sched, state.sched_idx,
                                              hedge_ratio, spot0)
        if K_next <= 0.0:   # loan fully repaid ⇒ stop hedging
            state.monthly_caps.append(0.0)
            state.K_prev = state.prem_prev = 0.0
            record_tape(state, month_no+1, day/365, 0.0, payoff, pnl, 0.0)
            continue

        # ── price new option & capital req ---------------------------
        rv      = realised_vol(state.last_7)
        iv      = lookup_iv_weekly(weekly_tbl, rv, K_next/state.spot)
        premium = bs_price(state.spot, K_next, hedge_interval_days/365, r, iv,
                           call=False)
        cap_req = max(0.0, premium - payoff)

        state.monthly_caps.append(cap_req)
        state.max_monthly_cap = max(state.max_monthly_cap, cap_req)

        total_premium_cost += premium

        record_tape(state, month_no+1, day/365, iv, payoff, pnl, cap_req)

        state.K_prev   = K_next
        state.prem_prev= premium

    # ── aggregate results ─────────────────────────────────────────────
    avg_monthly_cap = float(np.mean(state.monthly_caps))

    if debug:
        return (state.cum_pnl, state.max_monthly_cap, avg_monthly_cap,
                state.spot, state.min_price, state.max_price, state.tape)

    months_logged = len(state.monthly_caps)-1
    mpy = months_logged//years if months_logged else 0
    caps_mat = (np.array(state.monthly_caps[1:1+years*mpy]).reshape(years, mpy)
                if mpy else np.zeros((years,1)))

    yearly_avg_caps = caps_mat.mean(axis=1).tolist()
    yearly_max_caps = caps_mat.max(axis=1).tolist()

    return (state.cum_pnl, state.max_monthly_cap, avg_monthly_cap,
            state.spot, state.min_price, state.max_price,
            state.yearly_pnls, yearly_avg_caps, yearly_max_caps,
            total_premium_cost, defaulted, default_month)

# ────────────────────────── CLI / driver  ───────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--surface",       required=True, help="SVI surface CSV")
    p.add_argument("--price",         required=True, help="Spot price CSV")
    p.add_argument("--years",         type=int, default=5, help="Horizon (years)")
    p.add_argument("--n_paths",       type=int, default=1000, help="MC runs")
    p.add_argument("--hedge_ratio",   type=float, default=0.8,
                   help="Initial strike/spot ratio (legacy mode)")
    p.add_argument("--steps_per_year",type=int, default=12, help="Re‑hedge freq")
    p.add_argument("--s0",            type=float, default=100_000,
                   help="Initial BTC spot (USD)")
    p.add_argument("--rate",          type=float, default=0.0, help="Risk‑free r")
    # loan params
    p.add_argument("--loan_rate",     type=float, default=0.10,
                   help="Annual loan interest (e.g. 0.10 = 10 %)")
    p.add_argument("--sizing_rate", type=float, default=0.15,
                   help="Annual rate for payment sizing (billing ceiling)")
    p.add_argument("--principal",     type=float, default=None,
                   help="Loan principal (defaults s0×hedge_ratio)")
    p.add_argument("--debug",         action="store_true",
                   help="Run a single path verbosely")
    p.add_argument("--seed",          type=int, default=None, help="Random seed")
    return p.parse_args()


def main() -> None:
    cfg = parse_args()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s",
                        level=logging.INFO)

    surface = load_surface(Path(cfg.surface))
    price   = load_price(Path(cfg.price))

    mu, sigma_hist = calibrate_hist_mu_sigma(price)
    logging.info("Annualised μ = %.3f   σ = %.3f", mu, sigma_hist)

    hedge_days = 365 // cfg.steps_per_year
    weekly_tbl = build_weekly_iv_table(surface, price, tenor_days=hedge_days)

    rng = np.random.default_rng(cfg.seed)

    principal = cfg.principal if cfg.principal is not None else cfg.s0*cfg.hedge_ratio
    amort_sched = build_amortisation_schedule(principal, cfg.sizing_rate,
                                              cfg.years, cfg.steps_per_year,
                                              accrual_rate=cfg.loan_rate)

    # ── DEBUG single path ────────────────────────────────────────────
    if cfg.debug:
        out = simulate_one_path(rng, weekly_tbl, cfg.s0, mu, sigma_hist,
                                cfg.years, hedge_days, cfg.hedge_ratio,
                                cfg.rate, True, amort_sched,
                                cfg.loan_rate, cfg.sizing_rate, cfg.steps_per_year)
        (pnl, mcap, amcap, fpx, mnpx, mxpx, tape) = out  # type: ignore
        print("\n── DEBUG SUMMARY ───────────────────────────────────────────")
        print(f"Total {cfg.years}-yr P&L      : {pnl:,.2f}")
        print(f"Max monthly capital           : {mcap:,.2f}")
        print(f"Average monthly capital       : {amcap:,.2f}")
        print(f"Final / min / max BTC price   : {fpx:,.2f} / {mnpx:,.2f} / {mxpx:,.2f}")

        df = pd.DataFrame(tape)
        pd.set_option("display.max_rows", None)
        print("\n── MONTH‑BY‑MONTH TAPE ─────────────────────────────────────")
        print(df.to_string(index=False))
        return

    # ── Monte‑Carlo loop ─────────────────────────────────────────────
    n, yrs = cfg.n_paths, cfg.years
    arrays = {
        "net_pnl":           np.empty(n),
        "max_cap":           np.empty(n),
        "avg_cap":           np.empty(n),
        "final_px":          np.empty(n),
        "min_px":            np.empty(n),
        "max_px":            np.empty(n),
        "tot_prem":          np.empty(n),
        "defaulted":         np.empty(n, dtype=bool),
        "def_month":         np.empty(n, dtype=int),
        "yr_pnl":            np.empty((n, yrs)),
        "yr_avg_cap":        np.empty((n, yrs)),
        "yr_max_cap":        np.empty((n, yrs)),
    }

    for i in range(n):
        (pnl, mcap, amcap, fpx, mnpx, mxpx,
         ypnls, yavgc, ymaxc,
         tot_prem, def_flg, def_mth) = simulate_one_path(
            rng, weekly_tbl, cfg.s0, mu, sigma_hist,
            yrs, hedge_days, cfg.hedge_ratio,
            cfg.rate, False, amort_sched,
            cfg.loan_rate, cfg.sizing_rate, cfg.steps_per_year)

        arrays["net_pnl"][i]    = pnl
        arrays["max_cap"][i]    = mcap
        arrays["avg_cap"][i]    = amcap
        arrays["final_px"][i]   = fpx
        arrays["min_px"][i]     = mnpx
        arrays["max_px"][i]     = mxpx
        arrays["tot_prem"][i]   = tot_prem
        arrays["defaulted"][i]  = def_flg
        arrays["def_month"][i]  = def_mth
        arrays["yr_pnl"][i]     = ypnls
        arrays["yr_avg_cap"][i] = yavgc
        arrays["yr_max_cap"][i] = ymaxc

    # ── top‑level stats ──────────────────────────────────────────────
    defaults = arrays["defaulted"]
    pct_default = defaults.mean()*100
    prem_def    = arrays["tot_prem"][defaults]

    print(f"\nMonte‑Carlo results  ({n:,} paths, {yrs} yrs):")
    print(f"  % paths defaulted             : {pct_default:.2f} %")
    if defaults.any():
        print(f"  Avg put spend (defaulted)     : {prem_def.mean():,.2f}")
        print(f"  Max put spend (defaulted)     : {prem_def.max():,.2f}")
        print(f"  Avg default month             : {arrays['def_month'][defaults].mean():.1f}")
    else:
        print("  No defaults observed 🤷‍♂️")

    # legacy metrics preserved ------------------------------------------------
    net_pnls = arrays["net_pnl"]
    loss_95, loss_99 = np.percentile(net_pnls, [5,1])
    avg_monthly_pnl = net_pnls.mean() / (yrs*12)

    print(f"  Mean total net P&L per path   : {net_pnls.mean():,.2f}")
    print(f"  95th / 99th % gains           : {np.percentile(net_pnls,95):,.2f} / {np.percentile(net_pnls,99):,.2f}")
    print(f"  95th / 99th % losses          : {loss_95:,.2f} / {loss_99:,.2f}")
    print(f"  Average monthly P&L           : {avg_monthly_pnl:,.2f}")

    # per‑year aggregates ----------------------------------------------------
    for yr in range(1, yrs+1):
        print(f"  Year {yr}:  avg P&L = {arrays['yr_pnl'][:,yr-1].mean():,.2f} | "
              f"avg monthly cap = {arrays['yr_avg_cap'][:,yr-1].mean():,.2f} | "
              f"mean max cap = {arrays['yr_max_cap'][:,yr-1].mean():,.2f}")

    # ── CSV one‑liner -------------------------------------------------------
    today = date.today().strftime("%Y%m%d")
    out_dir = Path("result"); out_dir.mkdir(exist_ok=True)

    rec: Dict[str, Any] = {
        "pct_default": pct_default,
        "avg_put_spend_default": float(prem_def.mean()) if defaults.any() else 0.0,
        "max_put_spend_default": float(prem_def.max())  if defaults.any() else 0.0,
        "avg_default_month": float(arrays['def_month'][defaults].mean()) if defaults.any() else 0.0,
        "mean_total_net_pnl": float(net_pnls.mean()),
        "pct95_gain": float(np.percentile(net_pnls,95)),
        "pct99_gain": float(np.percentile(net_pnls,99)),
        "pct5_loss": float(loss_95),
        "pct1_loss": float(loss_99),
        "avg_monthly_pnl": float(avg_monthly_pnl),
    }
    pd.DataFrame([rec]).to_csv(out_dir/f"summary_{today}.csv", index=False)
    print(f"\nSummary saved to result/summary_{today}.csv")


if __name__ == "__main__":
    main()
