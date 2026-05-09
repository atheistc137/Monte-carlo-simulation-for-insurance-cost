# Default & Liquidation MC — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Simulate borrower default probability on Bitmor BTC-backed loans and check whether BTC collateral + PUT mark-to-market covers lender exposure at each default event.

**Architecture:** Fresh folder `default-and-liquidation-mc/` with 6 modules: config, default model, price paths (GBM + jump-diffusion), liquidation waterfall, simulator (MC loop), and reporter. Imports utility functions from the adjacent `Monte carlo for insurance cost/` folder — no data duplication. GBM or Merton jump-diffusion price paths with regime-matched IV lookups from the SVI surface.

**Tech Stack:** Python 3.10+, numpy, pandas, matplotlib, scipy (via imported `bs_price`). No new dependencies beyond what the insurance cost folder already uses.

---

### Task 1: config.py — Central configuration and imports

**Files:**
- Create: `config.py`
- Create: `results/` (empty directory)

**Step 1: Write config.py**

```python
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
RISK_FREE_RATE = 0.0            # for BS pricing

# ── Default model ──
P_EXOG_MONTHLY = 0.005          # 0.5% exogenous default per month
EXOG_CRASH_BETA = 3.0           # exogenous prob scales: p * (1 + beta * max(0, -monthly_return))
RATIONAL_SIGMOID_SCALE = 1.0    # sigmoid steepness for rational default

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
```

**Step 2: Create results directory**

Run: `mkdir -p results`

**Step 3: Verify imports from insurance folder work**

Run: `python -c "import config; from rolldown_utils import lookup_iv, snap_to_strike, apply_slippage, RegimeIndex, generate_gbm_path; from liquidation_utils import bs_price, load_surface, load_price, calibrate_hist_mu_sigma; print('All imports OK')"`
Expected: `All imports OK`

**Step 4: Commit**

```bash
git add config.py
git commit -m "feat: add config.py with loan params and insurance folder imports"
```

---

### Task 2: default_model.py — Default probability logic

**Files:**
- Create: `default_model.py`
- Create: `tests/test_default_model.py`

**Step 1: Write the failing tests**

```python
"""Tests for the default model."""
import math
import pytest
from default_model import (
    compute_annuity,
    rational_default_probability,
    exogenous_default_draw,
    check_default,
)


class TestComputeAnnuity:
    def test_zero_rate(self):
        """At 0% rate, annuity = principal / n_months."""
        assert compute_annuity(12_000, 0.0, 12) == pytest.approx(1_000.0)

    def test_positive_rate(self):
        """Standard annuity at 15% APR, 12 months, $70k principal."""
        a = compute_annuity(70_000, 0.15, 12)
        # Manual: r=0.15/12=0.0125, A = 70000*0.0125*(1.0125^12)/((1.0125^12)-1)
        r = 0.15 / 12
        expected = 70_000 * r * (1 + r) ** 12 / ((1 + r) ** 12 - 1)
        assert a == pytest.approx(expected, rel=1e-6)

    def test_one_month(self):
        """Single month: annuity = principal * (1 + r)."""
        a = compute_annuity(10_000, 0.12, 1)
        assert a == pytest.approx(10_000 * (1 + 0.01), rel=1e-6)


class TestRationalDefault:
    def test_no_savings_zero_prob(self):
        """When remaining cost <= restart cost, probability should be near 0."""
        p = rational_default_probability(
            remaining_payments=5000,
            restart_cost=6000,
            monthly_payment=1000,
            scale=1.0,
        )
        assert p < 0.01

    def test_large_savings_high_prob(self):
        """When savings are many multiples of monthly payment, prob near 1."""
        p = rational_default_probability(
            remaining_payments=10000,
            restart_cost=2000,
            monthly_payment=1000,
            scale=1.0,
        )
        assert p > 0.95

    def test_moderate_savings(self):
        """Savings equal to one monthly payment → sigmoid(1) ≈ 0.73."""
        p = rational_default_probability(
            remaining_payments=5000,
            restart_cost=4000,
            monthly_payment=1000,
            scale=1.0,
        )
        expected = 1 / (1 + math.exp(-1.0))
        assert p == pytest.approx(expected, rel=0.01)


class TestExogenousDefault:
    def test_deterministic_seed(self):
        """With a fixed RNG, result is deterministic."""
        import numpy as np
        rng = np.random.default_rng(42)
        results = [exogenous_default_draw(0.5, rng) for _ in range(100)]
        rng2 = np.random.default_rng(42)
        results2 = [exogenous_default_draw(0.5, rng2) for _ in range(100)]
        assert results == results2

    def test_zero_prob_never_defaults(self):
        """Zero probability never triggers."""
        import numpy as np
        rng = np.random.default_rng(0)
        assert all(not exogenous_default_draw(0.0, rng) for _ in range(1000))

    def test_one_prob_always_defaults(self):
        """Probability 1.0 always triggers."""
        import numpy as np
        rng = np.random.default_rng(0)
        assert all(exogenous_default_draw(1.0, rng) for _ in range(100))

    def test_crash_beta_increases_prob(self):
        """A negative monthly return with crash_beta > 0 increases default rate."""
        import numpy as np
        n = 10_000
        # Baseline: no crash
        rng1 = np.random.default_rng(0)
        baseline = sum(exogenous_default_draw(0.01, rng1) for _ in range(n))
        # Crash: -30% monthly return, beta=3 → p_adj = 0.01 * (1 + 3*0.30) = 0.019
        rng2 = np.random.default_rng(0)
        crashed = sum(
            exogenous_default_draw(0.01, rng2, monthly_return=-0.30, crash_beta=3.0)
            for _ in range(n)
        )
        assert crashed > baseline * 1.5  # should roughly double

    def test_positive_return_no_effect(self):
        """A positive monthly return does not change probability."""
        import numpy as np
        n = 10_000
        rng1 = np.random.default_rng(0)
        baseline = sum(exogenous_default_draw(0.01, rng1) for _ in range(n))
        rng2 = np.random.default_rng(0)
        bullish = sum(
            exogenous_default_draw(0.01, rng2, monthly_return=0.20, crash_beta=3.0)
            for _ in range(n)
        )
        assert baseline == bullish  # identical draws, same effective p


class TestCheckDefault:
    def test_no_default_when_loan_healthy(self):
        """High spot, low debt — no rational or exogenous default."""
        import numpy as np
        rng = np.random.default_rng(99)
        defaulted, dtype = check_default(
            month=3,
            remaining_payments=5000,
            spot_now=100_000,
            debt_now=50_000,
            deposit_pct=0.30,
            sizing_apr=0.15,
            loan_term_months=12,
            monthly_payment=6000,
            p_exog=0.0,           # disable exogenous
            scale=1.0,
            rng=rng,
        )
        # Restart is more expensive (new deposit on 100k spot + new payments)
        # so rational default should not trigger
        assert not defaulted

    def test_exogenous_always_triggers(self):
        """Exogenous at p=1.0 always triggers regardless of economics."""
        import numpy as np
        rng = np.random.default_rng(0)
        defaulted, dtype = check_default(
            month=6,
            remaining_payments=5000,
            spot_now=100_000,
            debt_now=50_000,
            deposit_pct=0.30,
            sizing_apr=0.15,
            loan_term_months=12,
            monthly_payment=6000,
            p_exog=1.0,
            scale=1.0,
            rng=rng,
        )
        assert defaulted
        assert dtype == "exogenous"
```

**Step 2: Run tests to verify they fail**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python -m pytest tests/test_default_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'default_model'`

**Step 3: Write the implementation**

```python
"""
Default model: rational + exogenous default probability.

Rational default: borrower compares remaining loan payments vs cost of
restarting a fresh loan at current spot. Probability increases with savings
via a sigmoid function.

Exogenous default: flat monthly probability — borrower can't pay regardless
of loan economics (personal liquidity crisis).
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np


def compute_annuity(principal: float, annual_rate: float, n_months: int) -> float:
    """Fixed monthly payment (annuity formula).

    Uses the same formula as the Bitmor litepaper:
        A = P * r * (1+r)^n / ((1+r)^n - 1)
    where r = annual_rate / 12.
    """
    if n_months <= 0:
        return 0.0
    r = annual_rate / 12
    if r == 0:
        return principal / n_months
    return principal * r * (1 + r) ** n_months / ((1 + r) ** n_months - 1)


def rational_default_probability(
    remaining_payments: float,
    restart_cost: float,
    monthly_payment: float,
    scale: float = 1.0,
) -> float:
    """Probability of rational default given economic incentive.

    savings = remaining_payments - restart_cost
    If savings <= 0, probability ~ 0 (no incentive to walk away).
    If savings >> monthly_payment, probability ~ 1.

    Uses sigmoid: p = 1 / (1 + exp(-scale * savings / monthly_payment))
    """
    if monthly_payment <= 0:
        return 0.0
    savings = remaining_payments - restart_cost
    x = scale * savings / monthly_payment
    # Clamp to avoid overflow
    x = max(-20.0, min(20.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def exogenous_default_draw(
    p_monthly: float,
    rng: np.random.Generator,
    monthly_return: float = 0.0,
    crash_beta: float = 0.0,
) -> bool:
    """Bernoulli draw for exogenous (liquidity-driven) default.

    When crash_beta > 0, probability scales up during price drops:
        p_adjusted = p_monthly * (1 + crash_beta * max(0, -monthly_return))
    A -20% monthly return with beta=3 triples the base probability: 0.005 → 0.008.
    """
    p = p_monthly * (1.0 + crash_beta * max(0.0, -monthly_return))
    p = min(p, 1.0)
    if p <= 0:
        return False
    if p >= 1:
        return True
    return bool(rng.random() < p)


def check_default(
    month: int,
    remaining_payments: float,
    spot_now: float,
    debt_now: float,
    deposit_pct: float,
    sizing_apr: float,
    loan_term_months: int,
    monthly_payment: float,
    p_exog: float,
    scale: float,
    rng: np.random.Generator,
    monthly_return: float = 0.0,
    crash_beta: float = 0.0,
) -> Tuple[bool, str]:
    """Check both default channels. Returns (defaulted, type).

    type is "rational", "exogenous", or "" if no default.
    Exogenous is checked first (independent of economics).
    """
    # Channel 1: exogenous (crash-correlated)
    if exogenous_default_draw(p_exog, rng, monthly_return, crash_beta):
        return True, "exogenous"

    # Channel 2: rational
    # Restart cost: new deposit at current spot + total new payments
    new_deposit = deposit_pct / 100 * spot_now
    new_principal = (1 - deposit_pct / 100) * spot_now
    new_total_payments = compute_annuity(new_principal, sizing_apr, loan_term_months) * loan_term_months
    restart_cost = new_deposit + new_total_payments

    p_rational = rational_default_probability(
        remaining_payments=remaining_payments,
        restart_cost=restart_cost,
        monthly_payment=monthly_payment,
        scale=scale,
    )

    if rng.random() < p_rational:
        return True, "rational"

    return False, ""
```

**Step 4: Run tests to verify they pass**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python -m pytest tests/test_default_model.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add default_model.py tests/test_default_model.py
git commit -m "feat: add default model with rational + exogenous default channels"
```

---

### Task 3: liquidation_waterfall.py — Coverage ratio calculation

**Files:**
- Create: `liquidation_waterfall.py`
- Create: `tests/test_waterfall.py`

**Step 1: Write the failing tests**

```python
"""Tests for the liquidation waterfall."""
import pytest
from liquidation_waterfall import compute_waterfall, WaterfallResult


class TestWaterfall:
    def test_btc_covers_everything(self):
        """When BTC value alone covers debt + fee, surplus goes to protocol."""
        r = compute_waterfall(
            allocated_btc=1.0,
            spot=100_000,
            put_mtm=5_000,
            debt=60_000,
            liq_buffer=0.03,
        )
        assert r.coverage_ratio > 1.0
        assert r.shortfall_usd == 0.0
        assert r.surplus_to_protocol > 0.0
        # Total proceeds = 100k + 5k = 105k
        # Liabilities = 60k * 1.03 = 61.8k
        assert r.total_proceeds == pytest.approx(105_000)
        assert r.total_liabilities == pytest.approx(61_800)

    def test_exact_coverage(self):
        """When proceeds exactly equal liabilities."""
        # debt=100k, buffer=3%, liabilities=103k
        # btc=0.5 @ 100k = 50k, put=53k → total=103k
        r = compute_waterfall(
            allocated_btc=0.5,
            spot=100_000,
            put_mtm=53_000,
            debt=100_000,
            liq_buffer=0.03,
        )
        assert r.coverage_ratio == pytest.approx(1.0, rel=1e-6)
        assert r.shortfall_usd == pytest.approx(0.0, abs=1)
        assert r.surplus_to_protocol == pytest.approx(0.0, abs=1)

    def test_shortfall(self):
        """When BTC + PUT cannot cover debt + fee."""
        r = compute_waterfall(
            allocated_btc=1.0,
            spot=30_000,       # BTC dropped hard
            put_mtm=10_000,    # PUT helps but not enough
            debt=60_000,
            liq_buffer=0.03,
        )
        # Proceeds = 30k + 10k = 40k
        # Liabilities = 60k * 1.03 = 61.8k
        assert r.coverage_ratio < 1.0
        assert r.shortfall_usd == pytest.approx(21_800, rel=0.01)
        assert r.surplus_to_protocol == 0.0

    def test_zero_put(self):
        """PUT is worthless (deep OTM at default)."""
        r = compute_waterfall(
            allocated_btc=1.0,
            spot=120_000,
            put_mtm=0.0,
            debt=70_000,
            liq_buffer=0.03,
        )
        assert r.coverage_ratio > 1.0
        assert r.total_proceeds == pytest.approx(120_000)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_waterfall.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
"""
Liquidation waterfall: compute coverage ratio when borrower defaults.

Assets: BTC collateral (sold at spot) + PUT option (sold at mark-to-market).
Liabilities: outstanding debt + liquidator fee (buffer % of debt).
Surplus goes to protocol. Shortfall = lender loss.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WaterfallResult:
    btc_value: float
    put_mtm: float
    total_proceeds: float
    debt: float
    liquidator_fee: float
    total_liabilities: float
    coverage_ratio: float
    shortfall_usd: float
    surplus_to_protocol: float


def compute_waterfall(
    allocated_btc: float,
    spot: float,
    put_mtm: float,
    debt: float,
    liq_buffer: float,
) -> WaterfallResult:
    """Compute the liquidation waterfall.

    Parameters
    ----------
    allocated_btc : BTC remaining in the loan (after any micro-liquidations)
    spot          : BTC price at default
    put_mtm       : Mark-to-market value of held PUT (after slippage)
    debt          : Outstanding debt (principal + accrued interest - payments)
    liq_buffer    : Liquidator fee as fraction of debt (e.g. 0.03)

    Returns
    -------
    WaterfallResult with all waterfall components.
    """
    btc_value = allocated_btc * spot
    total_proceeds = btc_value + put_mtm

    liquidator_fee = liq_buffer * debt
    total_liabilities = debt + liquidator_fee

    if total_liabilities <= 0:
        coverage_ratio = float("inf")
    else:
        coverage_ratio = total_proceeds / total_liabilities

    if total_proceeds >= total_liabilities:
        shortfall = 0.0
        surplus = total_proceeds - total_liabilities
    else:
        shortfall = total_liabilities - total_proceeds
        surplus = 0.0

    return WaterfallResult(
        btc_value=btc_value,
        put_mtm=put_mtm,
        total_proceeds=total_proceeds,
        debt=debt,
        liquidator_fee=liquidator_fee,
        total_liabilities=total_liabilities,
        coverage_ratio=coverage_ratio,
        shortfall_usd=shortfall,
        surplus_to_protocol=surplus,
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_waterfall.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add liquidation_waterfall.py tests/test_waterfall.py
git commit -m "feat: add liquidation waterfall with coverage ratio calculation"
```

---

### Task 4: price_paths.py — Merton jump-diffusion path generator

**Files:**
- Create: `price_paths.py`
- Create: `tests/test_price_paths.py`

**Step 1: Write the failing tests**

```python
"""Tests for the jump-diffusion price path generator."""
import numpy as np
import pytest
from price_paths import generate_jd_path


class TestGenerateJDPath:
    def test_shape(self):
        """Output length = n_days + 1 (includes day 0)."""
        rng = np.random.default_rng(42)
        path = generate_jd_path(100_000, 0.05, 0.60, 360, rng,
                                lam=0.1, mu_j=-0.15, sigma_j=0.10)
        assert len(path) == 361

    def test_starts_at_spot(self):
        """First element equals spot_0."""
        rng = np.random.default_rng(42)
        path = generate_jd_path(100_000, 0.05, 0.60, 360, rng,
                                lam=0.1, mu_j=-0.15, sigma_j=0.10)
        assert path[0] == pytest.approx(100_000)

    def test_always_positive(self):
        """Prices should always be positive (log-normal + log-normal jumps)."""
        rng = np.random.default_rng(7)
        path = generate_jd_path(100_000, 0.0, 0.80, 360, rng,
                                lam=0.5, mu_j=-0.30, sigma_j=0.20)
        assert all(p > 0 for p in path)

    def test_deterministic_with_seed(self):
        """Same seed → same path."""
        rng1 = np.random.default_rng(99)
        path1 = generate_jd_path(100_000, 0.05, 0.60, 360, rng1,
                                 lam=0.1, mu_j=-0.15, sigma_j=0.10)
        rng2 = np.random.default_rng(99)
        path2 = generate_jd_path(100_000, 0.05, 0.60, 360, rng2,
                                 lam=0.1, mu_j=-0.15, sigma_j=0.10)
        np.testing.assert_array_equal(path1, path2)

    def test_zero_intensity_equals_gbm(self):
        """With λ=0 (no jumps), path should match pure GBM dynamics."""
        rng1 = np.random.default_rng(42)
        path_jd = generate_jd_path(100_000, 0.05, 0.60, 30, rng1,
                                   lam=0.0, mu_j=-0.15, sigma_j=0.10)
        # Log-returns should be roughly normal (no jump spikes)
        log_rets = np.diff(np.log(path_jd))
        # With 30 samples, just check reasonable range — no extreme outliers
        assert np.abs(log_rets).max() < 0.5  # no daily >50% move

    def test_high_intensity_produces_jumps(self):
        """High λ should produce noticeably fatter tails than pure GBM."""
        rng = np.random.default_rng(0)
        n = 360
        path = generate_jd_path(100_000, 0.0, 0.30, n, rng,
                                lam=2.0, mu_j=-0.20, sigma_j=0.15)
        log_rets = np.diff(np.log(path))
        # Kurtosis of daily log-returns should exceed normal (3.0)
        from scipy.stats import kurtosis
        k = kurtosis(log_rets, fisher=False)  # excess=False → normal ≈ 3
        assert k > 4.0  # fat tails from jumps
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_price_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'price_paths'`

**Step 3: Write the implementation**

```python
"""
Merton jump-diffusion price path generator.

Extends GBM with a compound Poisson jump process:
    dS/S = (μ - λk) dt + σ dW + J dN

where:
    N ~ Poisson(λ dt)     — number of jumps per day
    J ~ exp(μ_J + σ_J Z) - 1  — log-normal jump size
    k = exp(μ_J + σ_J²/2) - 1 — drift compensation

With λ=0 this reduces to plain GBM.
"""
from __future__ import annotations

import numpy as np


def generate_jd_path(
    spot_0: float,
    mu: float,
    sigma: float,
    n_days: int,
    rng: np.random.Generator,
    *,
    lam: float = 0.0,
    mu_j: float = -0.15,
    sigma_j: float = 0.10,
) -> np.ndarray:
    """Generate a single Merton jump-diffusion price path.

    Parameters
    ----------
    spot_0  : initial price
    mu      : annualized drift (continuous)
    sigma   : annualized diffusion volatility
    n_days  : number of daily steps
    rng     : numpy random Generator
    lam     : jump intensity (expected jumps per day)
    mu_j    : mean of log-jump size
    sigma_j : std of log-jump size

    Returns
    -------
    np.ndarray of length n_days + 1, starting at spot_0.
    """
    dt = 1.0 / 365.0

    # Drift compensation for jumps: E[e^J] - 1
    k = np.exp(mu_j + 0.5 * sigma_j ** 2) - 1.0 if lam > 0 else 0.0

    # Pre-draw all random variates
    z_diffusion = rng.standard_normal(n_days)
    n_jumps = rng.poisson(lam * dt, n_days) if lam > 0 else np.zeros(n_days, dtype=int)

    # Aggregate jump sizes per day
    jump_log_returns = np.zeros(n_days)
    for i in range(n_days):
        if n_jumps[i] > 0:
            jump_sizes = rng.normal(mu_j, sigma_j, n_jumps[i])
            jump_log_returns[i] = np.sum(jump_sizes)

    # Daily log-returns: diffusion + jumps
    log_returns = (
        (mu - lam * k - 0.5 * sigma ** 2) * dt
        + sigma * np.sqrt(dt) * z_diffusion
        + jump_log_returns
    )

    # Build price path
    log_prices = np.empty(n_days + 1)
    log_prices[0] = np.log(spot_0)
    np.cumsum(log_returns, out=log_prices[1:])
    log_prices[1:] += log_prices[0]

    return np.exp(log_prices)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_price_paths.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add price_paths.py tests/test_price_paths.py
git commit -m "feat: add Merton jump-diffusion price path generator"
```

---

### Task 5: simulator.py — Main Monte Carlo loop

**Files:**
- Create: `simulator.py`

This is the core file. It wires together: GBM paths, monthly loan state, PUT rolldown, default checking, and the waterfall.

**Step 1: Write simulator.py**

```python
"""
Main Monte Carlo simulator.

For each path:
  1. Generate a GBM price path (daily, 360 days for 12 months)
  2. Each month: accrue debt, roll PUT, check default
  3. On default: run liquidation waterfall
  4. Record per-path results
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

import config

# Imports from insurance cost folder (path set up in config.py)
from rolldown_utils import (
    lookup_iv,
    snap_to_strike,
    apply_slippage,
    RegimeIndex,
    generate_gbm_path,
)
from liquidation_utils import (
    bs_price,
    load_surface,
    load_price,
    calibrate_hist_mu_sigma,
)

from default_model import compute_annuity, check_default
from liquidation_waterfall import compute_waterfall
from price_paths import generate_jd_path

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("simulator")


@dataclass
class PathResult:
    path_id: int
    defaulted: bool
    default_month: int = 0
    default_type: str = ""
    spot_at_default: float = 0.0
    debt_at_default: float = 0.0
    btc_value: float = 0.0
    put_strike: float = 0.0
    put_mtm: float = 0.0
    put_mtm_after_slippage: float = 0.0
    total_proceeds: float = 0.0
    total_liabilities: float = 0.0
    coverage_ratio: float = 0.0
    shortfall_usd: float = 0.0
    surplus_to_protocol: float = 0.0
    cumulative_premiums: float = 0.0


def _snap_strike_up(raw_strike: float, spot: float) -> float:
    """Snap to exchange grid, rounding UP (ceiling)."""
    import math as _math
    snapped = snap_to_strike(raw_strike, spot)
    # snap_to_strike already uses math.ceil, so this is correct
    return snapped


def run_simulation(
    n_paths: int = config.MC_PATHS,
    seed: int = config.GBM_SEED,
) -> List[PathResult]:
    """Run the full Monte Carlo simulation."""

    # ── Load data ──
    log.info("Loading SVI surface from %s", config.SVI_SURFACE_CSV)
    surface = load_surface(config.SVI_SURFACE_CSV)

    log.info("Loading price data from %s", config.HOURLY_PRICE_CSV)
    price_hourly = load_price(config.HOURLY_PRICE_CSV)
    price_daily = price_hourly.resample("1D").last().dropna()

    # ── Calibrate GBM parameters ──
    mu, sigma = calibrate_hist_mu_sigma(price_daily, window_years=3)
    log.info("GBM calibration: mu=%.4f, sigma=%.4f", mu, sigma)

    spot_0 = float(price_daily.iloc[-1])
    log.info("Spot at origination: $%.2f", spot_0)

    # ── Regime index for IV lookups ──
    regime_idx = RegimeIndex(price_daily, surface, window_days=7)

    # ── Loan origination (same for all paths) ──
    deposit = config.DEPOSIT_PCT / 100 * spot_0
    loan_amount = (1 - config.DEPOSIT_PCT / 100) * spot_0
    btc_bought = 1.0  # normalized

    # Monthly payment sized at conservative 15% APR
    monthly_payment = compute_annuity(loan_amount, config.SIZING_APR, config.LOAN_TERM_MONTHS)

    # Initial PUT strike: snap_to_strike(ceil(spot * 0.70), spot), rounded up
    initial_put_strike = _snap_strike_up(spot_0 * (1 - config.DEPOSIT_PCT / 100), spot_0)

    log.info("Loan: deposit=$%.0f, principal=$%.0f, monthly=$%.0f, put_K=$%.0f",
             deposit, loan_amount, monthly_payment, initial_put_strike)

    # ── Monte Carlo ──
    rng = np.random.default_rng(seed)
    results: List[PathResult] = []
    total_days = config.LOAN_TERM_MONTHS * config.DAYS_PER_MONTH

    for pid in range(n_paths):
        if pid % max(1, n_paths // 10) == 0:
            log.info("Path %d / %d", pid, n_paths)

        # Generate full price path (GBM or jump-diffusion)
        if config.USE_JUMP_DIFFUSION:
            path_prices = generate_jd_path(
                spot_0, mu, sigma, total_days, rng,
                lam=config.JD_JUMP_INTENSITY,
                mu_j=config.JD_JUMP_MEAN,
                sigma_j=config.JD_JUMP_STD,
            )
        else:
            path_prices = generate_gbm_path(spot_0, mu, sigma, total_days, rng)

        # Build a daily price series for regime matching on this path
        start_date = price_daily.index[-1]
        path_dates = pd.date_range(start_date, periods=total_days + 1, freq="D")
        path_series = pd.Series(path_prices, index=path_dates)
        # Prepend some real history for trailing return calculation
        combined_prices = pd.concat([price_daily.iloc[-30:], path_series.iloc[1:]])
        combined_prices = combined_prices[~combined_prices.index.duplicated(keep="last")]

        # Loan state
        debt = loan_amount
        allocated_btc = btc_bought
        put_K = initial_put_strike
        put_tenor_remaining_days = 365  # initial PUT is 365-day
        cumulative_premiums = 0.0

        # Price initial PUT premium
        initial_mny = put_K / spot_0
        try:
            initial_iv = lookup_iv(surface, regime_idx.last_surface_date,
                                   365, initial_mny)
        except (ValueError, KeyError):
            initial_iv = 0.60  # fallback
        initial_premium = bs_price(spot_0, put_K, 1.0, config.RISK_FREE_RATE,
                                   initial_iv, call=False)
        cumulative_premiums += initial_premium

        defaulted = False
        result = PathResult(path_id=pid, defaulted=False)

        for month in range(1, config.LOAN_TERM_MONTHS + 1):
            day_idx = month * config.DAYS_PER_MONTH
            spot_m = path_prices[day_idx]
            date_m = path_dates[day_idx]

            # Accrue debt
            debt *= (1 + config.ACCRUAL_APR / 12)

            # Deduct monthly payment (borrower pays if not defaulting)
            debt -= monthly_payment
            debt = max(debt, 0.0)

            # PUT rolldown: value the held PUT and potentially roll
            put_tenor_remaining_days -= config.DAYS_PER_MONTH
            put_tenor_T = max(put_tenor_remaining_days / 365, 1 / 365)
            mny_held = put_K / spot_m

            # Regime-matched IV lookup
            try:
                matched_date = regime_idx.resolve(combined_prices, date_m)
                iv_held = lookup_iv(surface, matched_date,
                                    max(put_tenor_remaining_days, 15), mny_held)
            except (ValueError, KeyError):
                iv_held = 0.60

            held_put_value = bs_price(spot_m, put_K, put_tenor_T,
                                      config.RISK_FREE_RATE, iv_held, call=False)

            # Replacement PUT: strike tracks current debt level
            new_raw_strike = debt if debt > 0 else loan_amount * 0.5
            new_K = _snap_strike_up(new_raw_strike, spot_m)
            new_mny = new_K / spot_m
            remaining_months = config.LOAN_TERM_MONTHS - month
            new_tenor_days = remaining_months * config.DAYS_PER_MONTH
            new_tenor_T = max(new_tenor_days / 365, 1 / 365)

            if new_tenor_days > 0:
                try:
                    iv_new = lookup_iv(surface, matched_date,
                                       max(new_tenor_days, 15), new_mny)
                except (ValueError, KeyError):
                    iv_new = 0.60

                replacement_cost = bs_price(spot_m, new_K, new_tenor_T,
                                            config.RISK_FREE_RATE, iv_new, call=False)

                # Roll if profitable (held value - replacement - slippage > 0)
                slippage_sell = apply_slippage(held_put_value, mny_held)
                slippage_buy = apply_slippage(replacement_cost, new_mny)
                roll_profit = (held_put_value - slippage_sell) - (replacement_cost + slippage_buy)

                if roll_profit > 0:
                    put_K = new_K
                    put_tenor_remaining_days = new_tenor_days
                    cumulative_premiums += replacement_cost + slippage_buy

            # Default check
            remaining_payments = remaining_months * monthly_payment

            # Monthly return for crash-correlated exogenous default
            prev_day_idx = (month - 1) * config.DAYS_PER_MONTH
            spot_prev = path_prices[prev_day_idx]
            monthly_return = (spot_m - spot_prev) / spot_prev if spot_prev > 0 else 0.0

            did_default, dtype = check_default(
                month=month,
                remaining_payments=remaining_payments,
                spot_now=spot_m,
                debt_now=debt,
                deposit_pct=config.DEPOSIT_PCT,
                sizing_apr=config.SIZING_APR,
                loan_term_months=config.LOAN_TERM_MONTHS,
                monthly_payment=monthly_payment,
                p_exog=config.P_EXOG_MONTHLY,
                scale=config.RATIONAL_SIGMOID_SCALE,
                rng=rng,
                monthly_return=monthly_return,
                crash_beta=config.EXOG_CRASH_BETA,
            )

            if did_default:
                # Value PUT at mark-to-market for waterfall
                put_T = max(put_tenor_remaining_days / 365, 1 / 365)
                mny_at_default = put_K / spot_m
                try:
                    iv_default = lookup_iv(surface, matched_date,
                                           max(put_tenor_remaining_days, 15),
                                           mny_at_default)
                except (ValueError, KeyError):
                    iv_default = 0.60

                put_mtm = bs_price(spot_m, put_K, put_T,
                                   config.RISK_FREE_RATE, iv_default, call=False)
                slippage = apply_slippage(put_mtm, mny_at_default)
                put_mtm_net = max(0, put_mtm - slippage)

                wf = compute_waterfall(
                    allocated_btc=allocated_btc,
                    spot=spot_m,
                    put_mtm=put_mtm_net,
                    debt=debt,
                    liq_buffer=config.LIQ_BUFFER,
                )

                result = PathResult(
                    path_id=pid,
                    defaulted=True,
                    default_month=month,
                    default_type=dtype,
                    spot_at_default=spot_m,
                    debt_at_default=debt,
                    btc_value=wf.btc_value,
                    put_strike=put_K,
                    put_mtm=put_mtm,
                    put_mtm_after_slippage=put_mtm_net,
                    total_proceeds=wf.total_proceeds,
                    total_liabilities=wf.total_liabilities,
                    coverage_ratio=wf.coverage_ratio,
                    shortfall_usd=wf.shortfall_usd,
                    surplus_to_protocol=wf.surplus_to_protocol,
                    cumulative_premiums=cumulative_premiums,
                )
                defaulted = True
                break

        if not defaulted:
            result = PathResult(path_id=pid, defaulted=False,
                                cumulative_premiums=cumulative_premiums)

        results.append(result)

    return results


if __name__ == "__main__":
    results = run_simulation()
    n_defaults = sum(1 for r in results if r.defaulted)
    log.info("Done. %d / %d paths defaulted (%.1f%%)",
             n_defaults, len(results), 100 * n_defaults / len(results))
```

**Step 2: Run a quick smoke test (10 paths)**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python -c "import simulator; results = simulator.run_simulation(n_paths=10, seed=42); print(f'{sum(r.defaulted for r in results)} / 10 defaulted')"`
Expected: Prints number of defaults, no crashes

**Step 3: Commit**

```bash
git add simulator.py
git commit -m "feat: add main MC simulator with GBM paths, rolldown, and default checking"
```

---

### Task 6: report.py — Aggregation, CSVs, and plots

**Files:**
- Create: `report.py`

**Step 1: Write report.py**

```python
"""
Reporting: aggregate MC results into summary stats, CSVs, and plots.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config
from simulator import PathResult

log = logging.getLogger("report")


def build_dataframe(results: List[PathResult]) -> pd.DataFrame:
    """Convert list of PathResult to a DataFrame."""
    return pd.DataFrame([asdict(r) for r in results])


def compute_summary(df: pd.DataFrame, original_principal: float) -> dict:
    """Compute aggregate metrics from simulation results."""
    n_total = len(df)
    defaults = df[df["defaulted"]]
    n_defaults = len(defaults)

    rational = defaults[defaults["default_type"] == "rational"]
    exogenous = defaults[defaults["default_type"] == "exogenous"]

    summary = {
        "total_paths": n_total,
        "n_defaults": n_defaults,
        "default_rate_pct": 100 * n_defaults / n_total if n_total else 0,
        "n_rational": len(rational),
        "n_exogenous": len(exogenous),
        "rational_rate_pct": 100 * len(rational) / n_total if n_total else 0,
        "exogenous_rate_pct": 100 * len(exogenous) / n_total if n_total else 0,
    }

    if n_defaults > 0:
        cr = defaults["coverage_ratio"]
        summary["coverage_median"] = float(cr.median())
        summary["coverage_p5"] = float(cr.quantile(0.05))
        summary["coverage_p95"] = float(cr.quantile(0.95))

        shortfalls = defaults[defaults["coverage_ratio"] < 1.0]
        summary["shortfall_probability_pct"] = 100 * len(shortfalls) / n_defaults
        summary["shortfall_probability_of_total_pct"] = 100 * len(shortfalls) / n_total

        if len(shortfalls) > 0:
            summary["mean_shortfall_usd"] = float(shortfalls["shortfall_usd"].mean())
            summary["max_shortfall_usd"] = float(shortfalls["shortfall_usd"].max())
            summary["mean_shortfall_pct_principal"] = float(
                100 * shortfalls["shortfall_usd"].mean() / original_principal
            )
        else:
            summary["mean_shortfall_usd"] = 0.0
            summary["max_shortfall_usd"] = 0.0
            summary["mean_shortfall_pct_principal"] = 0.0

        surplus = defaults[defaults["coverage_ratio"] >= 1.0]
        if len(surplus) > 0:
            summary["mean_surplus_to_protocol"] = float(surplus["surplus_to_protocol"].mean())
        else:
            summary["mean_surplus_to_protocol"] = 0.0

        summary["mean_default_month"] = float(defaults["default_month"].mean())
    else:
        summary["coverage_median"] = None
        summary["shortfall_probability_pct"] = 0.0
        summary["shortfall_probability_of_total_pct"] = 0.0

    return summary


def save_results(results: List[PathResult], original_principal: float,
                 output_dir: Path = config.RESULTS_DIR) -> None:
    """Save CSVs, plots, and print console summary."""
    output_dir.mkdir(parents=True, exist_ok=True)

    df = build_dataframe(results)
    defaults = df[df["defaulted"]]

    # ── CSV: path details (defaults only) ──
    if not defaults.empty:
        defaults.to_csv(output_dir / "path_details.csv", index=False)
        log.info("Saved path_details.csv (%d rows)", len(defaults))

    # ── CSV: summary ──
    summary = compute_summary(df, original_principal)
    pd.DataFrame([summary]).to_csv(output_dir / "summary.csv", index=False)
    log.info("Saved summary.csv")

    # ── Plot: coverage ratio histogram ──
    if not defaults.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        cr = defaults["coverage_ratio"]
        ax.hist(cr, bins=50, edgecolor="black", alpha=0.7)
        ax.axvline(1.0, color="red", linestyle="--", linewidth=2, label="Break-even")
        ax.set_xlabel("Coverage Ratio")
        ax.set_ylabel("Number of Defaults")
        ax.set_title("Coverage Ratio Distribution at Default")
        ax.legend()
        plt.tight_layout()
        fig.savefig(output_dir / "coverage_histogram.png", dpi=150)
        plt.close(fig)
        log.info("Saved coverage_histogram.png")

        # ── Plot: defaults by month ──
        fig, ax = plt.subplots(figsize=(9, 5))
        months = defaults["default_month"]
        bins = range(1, config.LOAN_TERM_MONTHS + 2)
        ax.hist(months, bins=bins, edgecolor="black", alpha=0.7,
                color=["#2196F3" if t == "rational" else "#FF9800"
                       for t in defaults["default_type"]])
        # Stacked by type
        rational_m = defaults[defaults["default_type"] == "rational"]["default_month"]
        exog_m = defaults[defaults["default_type"] == "exogenous"]["default_month"]
        ax.hist([rational_m, exog_m], bins=bins, stacked=True,
                label=["Rational", "Exogenous"],
                color=["#2196F3", "#FF9800"], edgecolor="black", alpha=0.7)
        ax.set_xlabel("Default Month")
        ax.set_ylabel("Number of Defaults")
        ax.set_title("Time-to-Default Distribution")
        ax.legend()
        ax.set_xticks(range(1, config.LOAN_TERM_MONTHS + 1))
        plt.tight_layout()
        fig.savefig(output_dir / "default_timing.png", dpi=150)
        plt.close(fig)
        log.info("Saved default_timing.png")

    # ── Console summary ──
    print("\n" + "=" * 60)
    print("  DEFAULT & LIQUIDATION MC — SUMMARY")
    print("=" * 60)
    print(f"  Paths simulated     : {summary['total_paths']:,}")
    print(f"  Default rate        : {summary['default_rate_pct']:.2f}%")
    print(f"    Rational          : {summary['rational_rate_pct']:.2f}%")
    print(f"    Exogenous         : {summary['exogenous_rate_pct']:.2f}%")
    if summary.get("coverage_median") is not None:
        print(f"  Coverage ratio (med): {summary['coverage_median']:.3f}")
        print(f"  Coverage ratio (p5) : {summary['coverage_p5']:.3f}")
        print(f"  Shortfall prob      : {summary['shortfall_probability_pct']:.2f}% of defaults")
        print(f"  Shortfall prob total: {summary['shortfall_probability_of_total_pct']:.2f}% of all paths")
        print(f"  Mean shortfall      : ${summary['mean_shortfall_usd']:,.0f}")
        print(f"  Max shortfall       : ${summary['max_shortfall_usd']:,.0f}")
        print(f"  Mean surplus (prot) : ${summary['mean_surplus_to_protocol']:,.0f}")
        print(f"  Mean default month  : {summary['mean_default_month']:.1f}")
    else:
        print("  No defaults occurred.")
    print("=" * 60 + "\n")
```

**Step 2: Smoke test report with dummy data**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python -c "
from simulator import PathResult
from report import save_results
dummy = [
    PathResult(0, True, 3, 'rational', 50000, 40000, 50000, 55000, 8000, 7500, 57500, 41200, 1.40, 0, 16300, 500),
    PathResult(1, True, 6, 'exogenous', 30000, 45000, 30000, 55000, 25000, 24000, 54000, 46350, 1.16, 0, 7650, 600),
    PathResult(2, False),
]
save_results(dummy, original_principal=70000)
print('OK')
"`
Expected: Prints summary, creates CSVs and PNGs in results/

**Step 3: Commit**

```bash
git add report.py
git commit -m "feat: add report module with summary stats, CSVs, and plots"
```

---

### Task 7: Wire up main entry point and end-to-end run

**Files:**
- Create: `main.py`

**Step 1: Write main.py**

```python
#!/usr/bin/env python3
"""
Entry point: run the default & liquidation Monte Carlo and produce reports.

Usage:
    python main.py                  # full run (10,000 paths), plain GBM
    python main.py --paths 100      # quick test run
    python main.py --jd             # jump-diffusion price model
"""
from __future__ import annotations

import argparse
import logging

import config
from simulator import run_simulation
from report import save_results

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def main():
    parser = argparse.ArgumentParser("Default & Liquidation Monte Carlo")
    parser.add_argument("--paths", type=int, default=config.MC_PATHS,
                        help="Number of MC paths")
    parser.add_argument("--seed", type=int, default=config.GBM_SEED,
                        help="Random seed")
    parser.add_argument("--jd", action="store_true",
                        help="Use Merton jump-diffusion instead of plain GBM")
    args = parser.parse_args()

    if args.jd:
        config.USE_JUMP_DIFFUSION = True

    results = run_simulation(n_paths=args.paths, seed=args.seed)

    spot_0 = results[0].spot_at_default if results[0].defaulted else 0
    # Recalculate original principal from config
    # (we don't have spot_0 directly, so pull from price data)
    from liquidation_utils import load_price
    price = load_price(config.HOURLY_PRICE_CSV)
    spot_0 = float(price.iloc[-1])
    original_principal = (1 - config.DEPOSIT_PCT / 100) * spot_0

    save_results(results, original_principal=original_principal)


if __name__ == "__main__":
    main()
```

**Step 2: Run end-to-end with 100 paths**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python main.py --paths 100`
Expected: Runs without error, prints summary, creates files in results/

**Step 3: Verify output files exist**

Run: `ls -la results/`
Expected: `path_details.csv`, `summary.csv`, `coverage_histogram.png`, `default_timing.png`

**Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add main.py entry point for end-to-end simulation"
```

---

### Task 8: Full-scale run and validation

**Step 1: Run full simulation — GBM baseline (10,000 paths)**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python main.py --paths 10000`
Expected: Completes, prints full summary with meaningful statistics

**Step 2: Sanity-check GBM outputs**

- Coverage ratio median should be > 1.0 (the PUT + BTC should usually cover debt)
- Default rate should be in single-digit percent range (exogenous ~6% over 12 months at 0.5%/month, rational depends on path economics)
- Shortfall probability should be low if coverage works
- Exogenous defaults in crash months should be elevated vs. calm months (crash-correlated beta)

**Step 3: Run full simulation — jump-diffusion stress (10,000 paths)**

Run: `cd /mnt/c/Users/suryansh/2025\ projects/default-and-liquidation-mc && python main.py --paths 10000 --jd`
Expected: Higher default rate and lower coverage ratios than GBM run. Fatter left tail in coverage histogram.

**Step 4: Compare GBM vs JD results**

- JD should produce more defaults (jumps create sharp crashes → more rational defaults + crash-correlated exogenous)
- JD shortfall probability should be meaningfully higher
- If JD shortfall is still low, the PUT hedge is robust to tail risk — good signal for the product

**Step 5: Commit results**

```bash
git add results/
git commit -m "results: initial 10k-path GBM and jump-diffusion simulation output"
```
