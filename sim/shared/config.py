"""
Central configuration for the BTC-collateralised lending simulators.
All paths, loan parameters, and MC settings in one place.
"""
from __future__ import annotations

from pathlib import Path

# ── Path setup ──
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Data files
SVI_SURFACE_CSV  = REPO_ROOT / "data" / "btc_iv_surface_svi.csv"
HOURLY_PRICE_CSV = REPO_ROOT / "data" / "BTCUSDT_1h.csv"

# Output / artefacts
RESULTS_DIR    = REPO_ROOT / "results"
DASHBOARD_HTML = REPO_ROOT / "dashboard" / "bitmor-dashboard.html"

# ── Loan parameters ──
DEPOSIT_PCT       = 30                # 30% down payment
LOAN_TERM_MONTHS  = 12                # 12-month loan
ACCRUAL_APR       = 0.10              # 10% actual borrow rate
SIZING_APR        = 0.15              # 15% conservative payment sizing
LIQ_BUFFER        = 0.03              # 3% liquidator fee
STRIKE_BUFFER     = 0.03              # buy PUT 3% above debt for collateralisation buffer
RISK_FREE_RATE    = 0.0               # for BS pricing
MIN_ROLL_PROFIT   = 20.0              # minimum $ profit to execute a PUT rolldown

# ── Price model ──
USE_JUMP_DIFFUSION = False            # True → Merton jump-diffusion; False → plain GBM
JD_JUMP_INTENSITY  = 0.10             # λ
JD_JUMP_MEAN       = -0.15            # μ_J
JD_JUMP_STD        = 0.10             # σ_J

# ── Monte Carlo ──
MC_PATHS       = 10_000
GBM_SEED       = 42
DAYS_PER_MONTH = 30
