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
LOOKBACK_DAYS    = 365*5
CURRENCY         = "BTC"
CSV_FILE         = "data/btc_iv_surface2.csv"
PNG_DIR          = pathlib.Path("results/surfaces")
RATE_LIMIT_SLEEP = 0.20                    # ≤10 req/s

API_ROOT = "https://history.deribit.com/api/v2/public"

PNG_DIR.mkdir(parents=True, exist_ok=True)
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


def quarterly_expiries(ref_date: dt.date) -> list[dt.date]:
    """Return the next 4 quarterly (Mar/Jun/Sep/Dec) last-Fridays after ref_date."""
    quarter_months = [3, 6, 9, 12]
    candidates: list[dt.date] = []
    for year in [ref_date.year, ref_date.year + 1, ref_date.year + 2]:
        for m in quarter_months:
            exp = last_friday(year, m)
            if exp > ref_date:
                candidates.append(exp)
    candidates.sort()
    return candidates[:4]


# Month abbreviation map for Deribit instrument names
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_expiry_from_instrument(name: str) -> str | None:
    """Extract expiry date ISO string from Deribit instrument name.

    E.g. 'BTC-27JUN25-100000-C' -> '2025-06-27'
    """
    parts = name.split("-")
    if len(parts) < 2:
        return None
    token = parts[1]  # e.g. '27JUN25'
    try:
        day_str = token[:len(token) - 5]   # '27'
        mon_str = token[-5:-2]              # 'JUN'
        yr_str  = token[-2:]                # '25'
        d = dt.date(2000 + int(yr_str), _MONTH_MAP[mon_str], int(day_str))
        return d.isoformat()
    except (KeyError, ValueError, IndexError):
        return None


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


def collect_surface_bulk(day: dt.date, expiry_dates: list[dt.date]) -> pd.DataFrame:
    """Fetch ALL BTC option trades for one UTC day via currency-level endpoint,
    keep last trade per instrument, filter to target expiries locally."""
    day_start = dt.datetime.combine(day, dt.time(0, tzinfo=timezone.utc))
    start_ms  = int(day_start.timestamp() * 1000)
    end_ms    = start_ms + 86_400_000 - 1

    all_trades: list[dict] = []
    has_more = True
    params = {
        "currency": CURRENCY, "kind": "option",
        "start_timestamp": start_ms, "end_timestamp": end_ms,
        "include_old": True, "count": 1000, "sorting": "asc",
    }
    while has_more:
        res = call_api("get_last_trades_by_currency_and_time", params)
        trades = res.get("trades", [])
        all_trades.extend(trades)
        has_more = res.get("has_more", False)
        if trades:
            params["start_timestamp"] = trades[-1]["timestamp"] + 1
        time.sleep(RATE_LIMIT_SLEEP)

    if not all_trades:
        return pd.DataFrame()

    # Last trade per instrument for this day
    df = pd.DataFrame(all_trades)
    df = df.sort_values("timestamp").groupby("instrument_name").last().reset_index()

    # Filter to target expiries
    expiry_set = {e.isoformat() for e in expiry_dates}
    rows = []
    for _, t in df.iterrows():
        inst_expiry = parse_expiry_from_instrument(t["instrument_name"])
        if inst_expiry not in expiry_set or t.get("iv") is None:
            continue
        # Extract strike and option_type from instrument name
        parts = t["instrument_name"].split("-")
        strike = float(parts[2])
        option_type = "call" if parts[3] == "C" else "put"
        expiry_date = dt.date.fromisoformat(inst_expiry)
        ttm_days = (dt.datetime.combine(expiry_date, dt.time(0)) -
                    dt.datetime.combine(day, dt.time(0))).days
        rows.append({
            "date":        day.isoformat(),
            "expiry":      inst_expiry,
            "instrument":  t["instrument_name"],
            "strike":      strike,
            "option_type": option_type,
            "ttm_days":    ttm_days,
            "iv":          float(t["iv"]),
            "price":       float(t["price"]),
        })

    return pd.DataFrame(rows)


def append_csv(df: pd.DataFrame) -> None:
    pathlib.Path(CSV_FILE).parent.mkdir(parents=True, exist_ok=True)
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
def day_already_in_csv(day: dt.date) -> bool:
    """Check if a day's data is already in the CSV (checkpoint/resume)."""
    if not pathlib.Path(CSV_FILE).exists():
        return False
    try:
        # Read only the date column for speed
        dates = pd.read_csv(CSV_FILE, usecols=["date"])["date"].unique()
        return day.isoformat() in dates
    except (KeyError, pd.errors.EmptyDataError):
        return False


def main() -> None:
    today = dt.datetime.now(timezone.utc).date()

    # Pre-load existing dates for checkpoint/resume
    existing_dates: set[str] = set()
    if pathlib.Path(CSV_FILE).exists():
        try:
            existing_dates = set(
                pd.read_csv(CSV_FILE, usecols=["date"])["date"].unique()
            )
        except (KeyError, pd.errors.EmptyDataError):
            pass
    print(f"  {len(existing_dates)} days already fetched (checkpoint).")

    for delta in range(1, LOOKBACK_DAYS + 1):
        day = today - dt.timedelta(days=delta)

        if day.isoformat() in existing_dates:
            continue  # checkpoint: skip fetched days

        targets = [month_end_expiry(day)] + quarterly_expiries(day)
        print(f"{day}  → {len(targets)} target expiries …", end="", flush=True)

        df = collect_surface_bulk(day, targets)
        if df.empty:
            print("  no trades")
            continue

        append_csv(df)
        print(f"  {len(df):,} points")


if __name__ == "__main__":
    main()
