import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_surface():
    """IV surface with quarterly tenors, indexed like load_surface() output.

    Columns after set_index: iv (percentage, e.g. 50.0 = 50%).
    Index levels: (date, ttm_days, mny).
    """
    dates = pd.date_range("2024-01-01", "2025-03-01", freq="MS")
    ttm_values = [90, 180, 270, 365]
    mny_values = np.arange(0.4, 1.6, 0.1).round(1)

    rows = []
    for d in dates:
        for ttm in ttm_values:
            for mny in mny_values:
                # Simple smile: higher IV for OTM puts, slight term-structure decline
                iv = 50.0 + 20.0 * max(0.0, 1.0 - mny) - 3.0 * (ttm / 365)
                rows.append({"date": d, "ttm_days": int(ttm), "mny": mny, "iv": iv})

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["ttm_days"] = df["ttm_days"].astype(int)
    return df.set_index(["date", "ttm_days", "mny"]).sort_index()


@pytest.fixture
def synthetic_prices():
    """Daily BTC prices: starts at $100k, mild random walk.

    Returns pd.Series indexed by date, like load_price().resample('1D').last().
    """
    dates = pd.date_range("2024-01-01", "2025-06-30", freq="D")
    rng = np.random.default_rng(42)
    log_returns = rng.normal(0.0002, 0.02, len(dates) - 1)
    prices = np.empty(len(dates))
    prices[0] = 100_000.0
    for i in range(1, len(dates)):
        prices[i] = prices[i - 1] * np.exp(log_returns[i - 1])
    return pd.Series(prices, index=dates, name="close")
