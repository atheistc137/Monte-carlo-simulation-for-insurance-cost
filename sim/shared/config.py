"""
Central configuration for the default & liquidation Monte Carlo.
All paths, loan parameters, and MC settings in one place.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ── Path setup: import utilities from the insurance cost folder ──
INSURANCE_COST_DIR = Path(__file__).resolve().parent.parent / "Monte carlo for insurance cost"
if str(INSURANCE_COST_DIR) not in sys.path:
    sys.path.insert(0, str(INSURANCE_COST_DIR))

# Data files (read in place, no duplication)
SVI_SURFACE_CSV = INSURANCE_COST_DIR / "btc_iv_surface_svi.csv"
HOURLY_PRICE_CSV = INSURANCE_COST_DIR / "BTCUSDT_1h.csv"

# ── Loan parameters ──
DEPOSIT_PCT = 30                # 30% down payment
LOAN_TERM_MONTHS = 12           # 12-month loan
ACCRUAL_APR = 0.10              # 10% actual borrow rate
SIZING_APR = 0.15               # 15% conservative payment sizing
LIQ_BUFFER = 0.03               # 3% liquidator fee
STRIKE_BUFFER = 0.03            # buy PUT 3% above debt for collateralisation buffer
RISK_FREE_RATE = 0.0            # for BS pricing
MIN_ROLL_PROFIT = 20.0          # minimum $ profit to execute a PUT rolldown

# ── Price model ──
USE_JUMP_DIFFUSION = False       # True → Merton jump-diffusion; False → plain GBM
JD_JUMP_INTENSITY = 0.10         # λ: expected 1.2 jumps / year (Poisson)
JD_JUMP_MEAN = -0.15             # μ_J: mean log-jump size (negative = crashes)
JD_JUMP_STD = 0.10               # σ_J: jump size volatility

# ── Monte Carlo ──
MC_PATHS = 10_000
GBM_SEED = 42
DAYS_PER_MONTH = 30

# ── Output ──
RESULTS_DIR = Path(__file__).resolve().parent / "results"
