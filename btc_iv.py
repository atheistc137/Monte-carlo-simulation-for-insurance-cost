#!/usr/bin/env python3
"""
Daily BTC IV surface for the *month-end* contract only.

• Pulls historical trades from Deribit’s cold-storage cluster
  (https://history.deribit.com).
• For each UTC day in the look-back window, chooses ONE expiry:
      – If the date is 1-20   → current month’s last-Friday contract
      – If the date is 21-EoM → next   month’s last-Friday contract
• Writes one tidy CSV row per strike & option-type for that contract,
  plus a 3-D scatter PNG of the surface.

Author  : you
Created : 2025-06-05
"""

from __future__ import annotations

import time
import pathlib
import datetime as dt
from datetime import timezone
from typing import Dict, List

import requests
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


# ───────────────────── USER SETTINGS ──────────────────────
LOOKBACK_DAYS    = 365*3
CURRENCY         = "BTC"
CSV_FILE         = "btc_iv_surface2.csv"
PNG_DIR          = pathlib.Path("surfaces")
RATE_LIMIT_SLEEP = 0.20                    # ≤10 req/s

API_ROOT = "https://history.deribit.com/api/v2/public"

PNG_DIR.mkdir(exist_ok=True)
session = requests.Session()


# ───────────────────── HELPER FUNCTIONS ───────────────────
def json_params(params: Dict) -> Dict:
    """Convert Python bool → 'true'/'false' for REST query-string."""
    return {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items()}


def call_api(method: str, params: Dict) -> Dict:
    url = f"{API_ROOT}/{method}"
    r   = session.get(url, params=json_params(params), timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data["result"]


def fetch_instruments() -> List[Dict]:
    """Active + recently-expired BTC option contracts."""
    instruments = []
    for expired in (False, True):
        chunk = call_api(
            "get_instruments",
            {"currency": CURRENCY, "kind": "option", "expired": expired},
        )
        instruments.extend(chunk)
        time.sleep(RATE_LIMIT_SLEEP)
    return instruments


def last_friday(year: int, month: int) -> dt.date:
    """Return the last Friday in the given month."""
    # Start from last calendar day, walk backwards to Friday (weekday==4).
    d = dt.date(year, month, 1)
    last_day = d.replace(day=28) + dt.timedelta(days=4)  # guarantees next month
    last_day = last_day - dt.timedelta(days=last_day.day)  # last day of month
    while last_day.weekday() != 4:                        # 4 == Friday
        last_day -= dt.timedelta(days=1)
    return last_day


def month_end_expiry(ref_date: dt.date) -> dt.date:
    """
    Pick target expiry per rules:
        1-20  → this month’s last Friday
        21-EoM→ next month’s last Friday
    """
    if ref_date.day <= 20:
        year, month = ref_date.year, ref_date.month
    else:  # roll to next month
        if ref_date.month == 12:
            year, month = ref_date.year + 1, 1
        else:
            year, month = ref_date.year, ref_date.month + 1
    return last_friday(year, month)


def last_trade_for_day(instr: str, start_ms: int, end_ms: int) -> Dict | None:
    res = call_api(
        "get_last_trades_by_instrument_and_time",
        {
            "instrument_name": instr,
            "start_timestamp": start_ms,
            "end_timestamp":   end_ms,
            "include_old":     True,
        },
    )
    trades = res.get("trades", [])
    return trades[-1] if trades else None  # newest in window


def collect_surface(day: dt.date, instruments: List[Dict]) -> pd.DataFrame:
    """
    Build surface for the single month-end expiry relevant to `day`.
    """
    expiry_date = month_end_expiry(day)

    day_start = dt.datetime.combine(day, dt.time(0, tzinfo=timezone.utc))
    start_ms  = int(day_start.timestamp() * 1000)
    end_ms    = start_ms + 86_400_000 - 1

    rows = []
    for inst in instruments:
        inst_expiry_date = dt.datetime.utcfromtimestamp(
            inst["expiration_timestamp"] / 1000
        ).date()

        if inst_expiry_date != expiry_date:
            continue                                   # skip wrong expiry

        if inst["creation_timestamp"] > start_ms or inst["expiration_timestamp"] <= start_ms:
            continue                                   # not yet listed / already expired

        trade = last_trade_for_day(inst["instrument_name"], start_ms, end_ms)
        if not trade or trade.get("iv") is None:
            continue

        ttm_days = (inst["expiration_timestamp"] - start_ms) / 86_400_000
        rows.append(
            {
                "date":        day.isoformat(),
                "expiry":      expiry_date.isoformat(),
                "instrument":  inst["instrument_name"],
                "strike":      inst["strike"],
                "option_type": inst["option_type"],
                "ttm_days":    ttm_days,
                "iv":          float(trade["iv"]),
                "price":       float(trade["price"]),
            }
        )
        time.sleep(RATE_LIMIT_SLEEP)
    return pd.DataFrame(rows)


def append_csv(df: pd.DataFrame) -> None:
    mode   = "a" if pathlib.Path(CSV_FILE).exists() else "w"
    header = mode == "w"
    df.to_csv(CSV_FILE, mode=mode, header=header, index=False, float_format="%.6f")


def plot_surface(df: pd.DataFrame, day: dt.date, expiry: dt.date) -> None:
    fig = plt.figure()
    ax  = fig.add_subplot(projection="3d")
    ax.scatter(df["strike"], df["ttm_days"], df["iv"], marker=".", alpha=0.8)
    ax.set_xlabel("Strike (USD)")
    ax.set_ylabel("TTM (days)")
    ax.set_zlabel("Implied Vol")
    ax.set_title(f"BTC IV Surface – {day} (exp {expiry})")
    fig.savefig(PNG_DIR / f"{day}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# ───────────────────── MAIN LOOP ─────────────────────
def main() -> None:
    print("Fetching instrument catalogue …")
    instruments = fetch_instruments()
    print(f"  {len(instruments):,} contracts loaded.")

    today = dt.datetime.now(timezone.utc).date()
    for delta in range(1, LOOKBACK_DAYS + 1):
        day = today - dt.timedelta(days=delta)
        expiry = month_end_expiry(day)
        print(f"{day}  → target expiry {expiry} …", end="", flush=True)

        df = collect_surface(day, instruments)
        if df.empty:
            print("  no trades")
            continue

        append_csv(df)
        plot_surface(df, day, expiry)
        print(f"  {len(df):,} points")


if __name__ == "__main__":
    main()
