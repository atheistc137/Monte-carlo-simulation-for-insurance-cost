# Repo Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge `default-and-liquidation-mc/` into the current repo, reorganise into a `sim/`/`dashboard/`/`tests/`/`data/`/`results/` layout, and ship a README — without breaking the Vercel dashboard or the existing test suite.

**Architecture:** Plain working-tree copy of the other repo (history abandoned). Files relocated via `git mv` to preserve filename history. Imports rewritten to absolute `sim.*` paths. `config.py` collapses its cross-repo `INSURANCE_COST_DIR` indirection to a single `REPO_ROOT`. Each subsystem becomes a runnable Python package via `python -m sim.<subsystem>.<module>`.

**Tech Stack:** Python 3 + pytest + Vercel static deploy + bash. No new tooling added.

**Spec:** `docs/superpowers/specs/2026-05-09-repo-consolidation-design.md`

**Working branch:** `consolidation` off `dashboard-rehaul`

---

## Pre-flight: Capture Baseline

**Files:** none modified.

- [ ] **Step 1: Create the working branch**

```bash
cd "/mnt/c/Users/suryansh/2025 projects/Monte carlo for insurance cost"
git checkout dashboard-rehaul
git pull --ff-only origin dashboard-rehaul   # only if upstream is reachable; ignore if it errors
git checkout -b consolidation
```

Expected: `Switched to a new branch 'consolidation'`.

- [ ] **Step 2: Capture baseline test status**

```bash
pytest tests/ --tb=no -q | tee /tmp/baseline-pytest.txt
```

Record the final summary line (e.g. `42 passed in 8.3s`). This is the regression target — the post-consolidation run must match or exceed it (minus the dropped `test_price_paths.py` once it's removed).

- [ ] **Step 3: Capture baseline dashboard render**

Open `bitmor-dashboard.html` in a browser. Walk through every tab. Note: which tabs exist, which charts render, any console errors. Take a screenshot of each tab if helpful. This is the post-consolidation visual regression target.

If anything is already broken before consolidation, **fix it on `dashboard-rehaul` first** and rebase `consolidation`. Do not consolidate on top of a broken dashboard.

- [ ] **Step 4: Verify the other repo is reachable**

```bash
ls "/mnt/c/Users/suryansh/2025 projects/default-and-liquidation-mc/"
```

Expected: directory listing showing `backtest_report.py`, `historical_backtest.py`, `config.py`, `tests/`, `docs/`, `results/`, etc.

---

## Task 1: Commit Working-Tree Cleanup

**Files:**
- Stage all `D` (deleted) entries currently in `git status` from `dashboard-rehaul`'s in-progress `old/` deletion.

- [ ] **Step 1: Inspect what's pending**

```bash
git status --short
```

Expected: long list of `D` entries for `old/`, `surfaces/`, `result/summary_*`, `Bitmor Litepaper (1).pdf`, etc., plus `M  bitmor-dashboard.html`.

- [ ] **Step 2: Decide on `bitmor-dashboard.html` modification**

```bash
git diff --stat bitmor-dashboard.html
```

If the diff is intentional (your dashboard work in progress), keep it staged. If it's stale, `git checkout -- bitmor-dashboard.html`.

- [ ] **Step 3: Stage all deletions plus the dashboard if you want it**

```bash
git add -u                                # stages every deletion
git add bitmor-dashboard.html             # only if you want the modification
```

- [ ] **Step 4: Verify staging**

```bash
git status --short
```

Expected: only `D` entries (and possibly `M  bitmor-dashboard.html`) — no untracked files yet.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: clean up working tree before consolidation

Stage the in-progress old/ and surfaces/ deletions from dashboard-rehaul
so the consolidation diffs are not polluted by unrelated cleanup.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Verify commit landed**

```bash
git log --oneline -3
```

Expected: top commit message starts with `chore: clean up working tree`.

---

## Task 2: Copy Files From `default-and-liquidation-mc`

**Files (all created at repo root, untracked initially):**
- `backtest_report.py`, `historical_backtest.py`, `run_backtest.py`, `liquidation_waterfall.py`, `config.py`
- `tests/test_price_paths.py`, `tests/test_waterfall.py`
- `docs/plans/2026-04-04-default-liquidation-mc-design.md`, `2026-04-04-implementation-plan.md`, `2026-04-05-historical-backtest-design.md`, `2026-04-05-historical-backtest-plan.md`, `2026-04-06-oi-liquidity-snapshot-design.md`
- `results/backtest/backtest_report.html`, `backtest_summary.csv`, `backtest_tab_fragment.html`, `daily_coverage.csv`, `worst_by_loan.csv`

The `__pycache__/`, `.pytest_cache/`, and `old/` directories are NOT copied.

- [ ] **Step 1: Copy source `.py` files**

```bash
SRC="/mnt/c/Users/suryansh/2025 projects/default-and-liquidation-mc"
DST="/mnt/c/Users/suryansh/2025 projects/Monte carlo for insurance cost"

cp "$SRC/backtest_report.py"      "$DST/"
cp "$SRC/historical_backtest.py"  "$DST/"
cp "$SRC/run_backtest.py"         "$DST/"
cp "$SRC/liquidation_waterfall.py" "$DST/"
cp "$SRC/config.py"               "$DST/"
```

- [ ] **Step 2: Copy test files**

```bash
cp "$SRC/tests/test_price_paths.py" "$DST/tests/"
cp "$SRC/tests/test_waterfall.py"   "$DST/tests/"
```

- [ ] **Step 3: Copy design docs**

```bash
cp "$SRC/docs/plans/2026-04-04-default-liquidation-mc-design.md"  "$DST/docs/plans/"
cp "$SRC/docs/plans/2026-04-04-implementation-plan.md"            "$DST/docs/plans/"
cp "$SRC/docs/plans/2026-04-05-historical-backtest-design.md"     "$DST/docs/plans/"
cp "$SRC/docs/plans/2026-04-05-historical-backtest-plan.md"       "$DST/docs/plans/"
cp "$SRC/docs/plans/2026-04-06-oi-liquidity-snapshot-design.md"   "$DST/docs/plans/"
```

- [ ] **Step 4: Copy backtest results**

```bash
mkdir -p "$DST/results/backtest"
cp -r "$SRC/results/backtest/." "$DST/results/backtest/"
```

- [ ] **Step 5: Verify nothing was missed**

```bash
cd "$DST"
ls backtest_report.py historical_backtest.py run_backtest.py liquidation_waterfall.py config.py
ls tests/test_price_paths.py tests/test_waterfall.py
ls docs/plans/2026-04-04-* docs/plans/2026-04-05-* docs/plans/2026-04-06-*
ls results/backtest/
```

Expected: all listings succeed, no `No such file` errors.

- [ ] **Step 6: Stage and commit**

`results/backtest/*` files are NOT staged. They're regenerable via `python -m sim.backtest.run_backtest`; the spec says `results/` is gitignored. Task 5 adds `results/` to `.gitignore` formally. The fragment + report HTMLs remain on local disk for immediate dashboard rebuilds; a fresh clone has to re-run the backtest, which is documented in the README.

```bash
git add backtest_report.py historical_backtest.py run_backtest.py liquidation_waterfall.py config.py
git add tests/test_price_paths.py tests/test_waterfall.py
git add docs/plans/2026-04-04-* docs/plans/2026-04-05-* docs/plans/2026-04-06-*

git status --short
```

Expected: `A` entries for the 5 .py files, 2 test files, 5 docs files. The `results/backtest/*` files appear as `??` (untracked) — leave them.

```bash
git commit -m "$(cat <<'EOF'
chore: copy default-and-liquidation-mc files into repo root

Plain working-tree copy of the other repo's tracked + untracked work.
Files land at the current repo root pre-relocation; Task 3 moves them
into the sim/ layout via git mv so rename history is preserved.

Backtest result artefacts under results/backtest/ are intentionally
left untracked (regenerable from run_backtest.py).

Source: ../default-and-liquidation-mc (working tree as of $(date +%Y-%m-%d))

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Confirm**

```bash
git log --oneline -3
git ls-files | grep -E "^(backtest_report|historical_backtest|run_backtest|liquidation_waterfall|config)\.py$"
```

Expected: top commit is the copy commit; `git ls-files` lists the 5 newly-tracked `.py` files.

---

## Task 3: Relocate Files Into Target Layout

All moves use `git mv` so rename detection preserves blame. Outcome: every existing simulator/test/data file lives in its final location; imports still broken (Task 4 fixes them).

**Files moved (source → destination):**

```
bitmor-dashboard.html          → dashboard/bitmor-dashboard.html
embed_csv_to_dashboard.py      → dashboard/embed_csv_to_dashboard.py

bitmor_rolldown_mc.py          → sim/rolldown/bitmor_rolldown_mc.py
rolldown_utils.py              → sim/rolldown/rolldown_utils.py

btc_iv.py                      → sim/ivsurface/btc_iv.py
iv_surface_svi.py              → sim/ivsurface/iv_surface_svi.py

liquidation_utils.py           → sim/liquidation/liquidation_utils.py
liquidation_waterfall.py       → sim/liquidation/liquidation_waterfall.py

backtest_report.py             → sim/backtest/backtest_report.py
historical_backtest.py         → sim/backtest/historical_backtest.py
run_backtest.py                → sim/backtest/run_backtest.py

config.py                      → sim/shared/config.py

tests/test_btc_iv.py           → tests/ivsurface/test_btc_iv.py
tests/test_iv_surface_svi.py   → tests/ivsurface/test_iv_surface_svi.py
tests/test_rolldown_mc.py      → tests/rolldown/test_rolldown_mc.py
tests/test_rolldown_utils.py   → tests/rolldown/test_rolldown_utils.py
tests/test_waterfall.py        → tests/backtest/test_waterfall.py
tests/test_price_paths.py      → DELETE (Task 4 removes; references non-existent price_paths.py)

BTCUSDT_1h.csv                 → data/BTCUSDT_1h.csv
btc_iv_surface2.csv            → data/btc_iv_surface2.csv
btc_iv_surface_svi.csv         → data/btc_iv_surface_svi.csv
btc_svi_params.csv             → data/btc_svi_params.csv

result/                        → results/                  (rename)
```

`tests/conftest.py`, `tests/test_integration.py` stay at `tests/` root.

- [ ] **Step 1: Create target directories**

```bash
cd "/mnt/c/Users/suryansh/2025 projects/Monte carlo for insurance cost"
mkdir -p dashboard sim/rolldown sim/ivsurface sim/liquidation sim/backtest sim/shared
mkdir -p tests/rolldown tests/ivsurface tests/backtest
mkdir -p data
```

- [ ] **Step 2: Move dashboard files**

```bash
git mv bitmor-dashboard.html dashboard/bitmor-dashboard.html
git mv embed_csv_to_dashboard.py dashboard/embed_csv_to_dashboard.py
```

- [ ] **Step 3: Move rolldown files**

```bash
git mv bitmor_rolldown_mc.py sim/rolldown/bitmor_rolldown_mc.py
git mv rolldown_utils.py     sim/rolldown/rolldown_utils.py
```

- [ ] **Step 4: Move IV surface files**

```bash
git mv btc_iv.py          sim/ivsurface/btc_iv.py
git mv iv_surface_svi.py  sim/ivsurface/iv_surface_svi.py
```

- [ ] **Step 5: Move liquidation files**

```bash
git mv liquidation_utils.py     sim/liquidation/liquidation_utils.py
git mv liquidation_waterfall.py sim/liquidation/liquidation_waterfall.py
```

- [ ] **Step 6: Move backtest files**

```bash
git mv backtest_report.py     sim/backtest/backtest_report.py
git mv historical_backtest.py sim/backtest/historical_backtest.py
git mv run_backtest.py        sim/backtest/run_backtest.py
```

- [ ] **Step 7: Move config**

```bash
git mv config.py sim/shared/config.py
```

- [ ] **Step 8: Move test files**

```bash
git mv tests/test_btc_iv.py         tests/ivsurface/test_btc_iv.py
git mv tests/test_iv_surface_svi.py tests/ivsurface/test_iv_surface_svi.py
git mv tests/test_rolldown_mc.py    tests/rolldown/test_rolldown_mc.py
git mv tests/test_rolldown_utils.py tests/rolldown/test_rolldown_utils.py
git mv tests/test_waterfall.py      tests/backtest/test_waterfall.py
```

- [ ] **Step 9: Drop the dead test**

`tests/test_price_paths.py` references `price_paths.py` which lived only in `default-and-liquidation-mc/old/` (the early simulator). The current backtest pipeline uses GBM helpers in `rolldown_utils.py`, not jump-diffusion, so this test is unreachable. Spec calls for dropping `old/` entirely; consequently this test goes too.

```bash
git rm tests/test_price_paths.py
```

- [ ] **Step 10: Move data CSVs**

The current `.gitignore` ignores `*.csv`, so these CSVs aren't tracked — `git mv` won't apply. Use plain `mv`. (Verify with `git ls-files BTCUSDT_1h.csv` — should be empty.)

```bash
mv BTCUSDT_1h.csv         data/BTCUSDT_1h.csv
mv btc_iv_surface2.csv    data/btc_iv_surface2.csv
mv btc_iv_surface_svi.csv data/btc_iv_surface_svi.csv
mv btc_svi_params.csv     data/btc_svi_params.csv
```

If any of those files don't exist (you've cleaned them up at some point), skip — they'll be regenerated by the simulators on the next run.

- [ ] **Step 11: Migrate `result/` contents into `results/`**

`results/` already exists from Task 2's copy of `results/backtest/`, so a plain `mv result results` would fail. Move the contents instead. `result/`'s contents are gitignored (`.gitignore` lists `result/` and `*.csv`), so we use plain `mv`, not `git mv`.

```bash
if [ -d result ]; then
    # Move whatever's inside (mostly old rolldown_tier*.csv files, all gitignored).
    mv result/* results/ 2>/dev/null || true
    rmdir result 2>/dev/null || true
fi
mkdir -p results
ls results/
```

Expected: `results/backtest/` (from Task 2) plus any `rolldown_tier*.csv` files that were in `result/`.

- [ ] **Step 12: Verify nothing is left at root that shouldn't be**

```bash
ls *.py 2>/dev/null
```

Expected: no output (no stray `.py` files at repo root).

```bash
ls dashboard/ sim/rolldown/ sim/ivsurface/ sim/liquidation/ sim/backtest/ sim/shared/
```

Expected: each directory has its files from the mapping table.

- [ ] **Step 13: Commit**

```bash
git status --short
```

Confirm: only `R` (renames) and `D` (test_price_paths deletion). No `M` (modifications) — this is pure relocation.

```bash
git commit -m "$(cat <<'EOF'
refactor: relocate files into sim/, dashboard/, data/, tests/ layout

Pure file moves via git mv (rename detection preserves blame). No code
edits in this commit; imports break here and are fixed in the next
commit. Dropped tests/test_price_paths.py — references price_paths.py
from the abandoned old/ folder, not used by current backtest pipeline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 14: Verify rename detection**

```bash
git log --oneline -1 --stat | head -30
git log --follow --oneline sim/rolldown/bitmor_rolldown_mc.py | head -5
```

Expected: stat shows `R100` rename markers; `--follow` shows commit history before the move.

---

## Task 4: Refactor Imports & Hardcoded Paths

**Files modified (the entire `sim/` and `tests/` tree, plus `dashboard/embed_csv_to_dashboard.py`):**

| File | Imports to change | Path strings to change |
|---|---|---|
| `sim/shared/config.py` | drop `sys.path.insert` block | `INSURANCE_COST_DIR` → `REPO_ROOT`; CSVs point to `data/`; add `DASHBOARD_HTML` |
| `sim/rolldown/rolldown_utils.py` | `from liquidation_utils import` → `from sim.liquidation.liquidation_utils import` | none |
| `sim/rolldown/bitmor_rolldown_mc.py` | `from liquidation_utils import` → `from sim.liquidation.liquidation_utils import`; `from rolldown_utils import` → `from sim.rolldown.rolldown_utils import` | `--surface` default → `data/btc_iv_surface_svi.csv`; `--price` default → `data/BTCUSDT_1h.csv`; `result/...` → `results/...`; `bitmor-dashboard.html` → `dashboard/bitmor-dashboard.html` |
| `sim/ivsurface/btc_iv.py` | none (no project imports) | `CSV_FILE = "btc_iv_surface2.csv"` → `"data/btc_iv_surface2.csv"`; `PNG_DIR = pathlib.Path("surfaces")` → `pathlib.Path("results/surfaces")` |
| `sim/ivsurface/iv_surface_svi.py` | none | `--opt`/`--px`/`--out_param`/`--out_surf` defaults → `data/<filename>` |
| `sim/liquidation/liquidation_utils.py` | none | none |
| `sim/liquidation/liquidation_waterfall.py` | none | none |
| `sim/backtest/historical_backtest.py` | `import config` → `from sim.shared import config`; `from liquidation_waterfall import` → `from sim.liquidation.liquidation_waterfall import`; `from rolldown_utils import` → `from sim.rolldown.rolldown_utils import`; `from liquidation_utils import` → `from sim.liquidation.liquidation_utils import` | none (uses `config.SVI_SURFACE_CSV` etc.) |
| `sim/backtest/backtest_report.py` | `import config` → `from sim.shared import config`; `from liquidation_utils import load_price` → `from sim.liquidation.liquidation_utils import load_price` | none (uses `config.RESULTS_DIR`) |
| `sim/backtest/run_backtest.py` | `import config` → `from sim.shared import config`; `from historical_backtest import run_backtest` → `from sim.backtest.historical_backtest import run_backtest`; `from backtest_report import save_backtest_results` → `from sim.backtest.backtest_report import save_backtest_results` | replace subprocess call to `embed_csv_to_dashboard.py` with `python -m dashboard.embed_csv_to_dashboard`; `config.INSURANCE_COST_DIR / "bitmor-dashboard.html"` → `config.DASHBOARD_HTML` |
| `dashboard/embed_csv_to_dashboard.py` | none | `--dashboard` default → `dashboard/bitmor-dashboard.html`; `result_dir = Path("result")` → `Path("results")` |
| `tests/conftest.py` | none (no project imports) | none |
| `tests/test_integration.py` | inspect file; rewrite any `from <module>` to `from sim.<sub>.<module>` | none |
| `tests/rolldown/test_rolldown_mc.py` | every `from bitmor_rolldown_mc import` → `from sim.rolldown.bitmor_rolldown_mc import`; `from liquidation_utils import` → `from sim.liquidation.liquidation_utils import` | none |
| `tests/rolldown/test_rolldown_utils.py` | every `from rolldown_utils import` → `from sim.rolldown.rolldown_utils import`; `from btc_iv import` → `from sim.ivsurface.btc_iv import` | none |
| `tests/ivsurface/test_btc_iv.py` | `from btc_iv import` → `from sim.ivsurface.btc_iv import` | none |
| `tests/ivsurface/test_iv_surface_svi.py` | `from iv_surface_svi import` → `from sim.ivsurface.iv_surface_svi import` | none |
| `tests/backtest/test_waterfall.py` | `from liquidation_waterfall import` → `from sim.liquidation.liquidation_waterfall import` | none |

**`__init__.py` files to create (empty):**
- `sim/__init__.py`
- `sim/rolldown/__init__.py`
- `sim/ivsurface/__init__.py`
- `sim/liquidation/__init__.py`
- `sim/backtest/__init__.py`
- `sim/shared/__init__.py`
- `dashboard/__init__.py`
- `tests/rolldown/__init__.py`
- `tests/ivsurface/__init__.py`
- `tests/backtest/__init__.py`

(`tests/__init__.py` already exists — verify in step 1.)

### 4a — Foundation: rewrite `sim/shared/config.py`

This is the file every backtest module imports. Doing it first means later steps can immediately verify imports resolve.

- [ ] **Step 1: Read current `config.py` (sanity check)**

```bash
cat sim/shared/config.py
```

Confirm it matches what you saw during brainstorming: `INSURANCE_COST_DIR`, `RESULTS_DIR`, the `sys.path.insert` block.

- [ ] **Step 2: Rewrite the entire file**

Replace `sim/shared/config.py` with:

```python
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
```

Changes from original:
- Removed `import sys` and `sys.path.insert(...)` block (no longer needed — proper packages now).
- Removed `INSURANCE_COST_DIR` (cross-repo bridge no longer exists).
- Added `REPO_ROOT` (computed from `__file__` — `sim/shared/config.py` → 3 parents up = repo root).
- `SVI_SURFACE_CSV` and `HOURLY_PRICE_CSV` now point to `REPO_ROOT / "data" / ...`.
- Added `DASHBOARD_HTML` for `run_backtest.py` to consume.
- All loan/MC constants preserved unchanged.

- [ ] **Step 3: Smoke-test config import**

```bash
python -c "from sim.shared import config; print(config.REPO_ROOT); print(config.SVI_SURFACE_CSV); print(config.DASHBOARD_HTML)"
```

Expected: three absolute paths, all rooted at `.../Monte carlo for insurance cost/`.

If `ImportError: No module named 'sim'`: you haven't created `__init__.py` files yet — do step 4b's `__init__.py` creation early, then retry.

### 4b — Create all `__init__.py` files

- [ ] **Step 1: Create empty package markers**

```bash
touch sim/__init__.py sim/rolldown/__init__.py sim/ivsurface/__init__.py \
      sim/liquidation/__init__.py sim/backtest/__init__.py sim/shared/__init__.py \
      dashboard/__init__.py \
      tests/rolldown/__init__.py tests/ivsurface/__init__.py tests/backtest/__init__.py
```

- [ ] **Step 2: Verify `tests/__init__.py` exists**

```bash
ls tests/__init__.py
```

Expected: file listed (it should already exist from the original repo).

- [ ] **Step 3: Re-run config smoke test**

```bash
python -c "from sim.shared import config; print(config.REPO_ROOT)"
```

Expected: prints `.../Monte carlo for insurance cost`.

### 4c — Rewrite simulator imports & paths

Apply the changes from the table above. Each file edit is small and surgical — use `Edit` tool with exact `old_string`/`new_string`. Do not paraphrase imports; copy the exact strings from the table.

- [ ] **Step 1: `sim/rolldown/rolldown_utils.py`**

Change line 12 from:
```python
from liquidation_utils import bs_price, build_weekly_iv_table
```
to:
```python
from sim.liquidation.liquidation_utils import bs_price, build_weekly_iv_table
```

- [ ] **Step 2: `sim/rolldown/bitmor_rolldown_mc.py` — imports**

Change line 19's import block from:
```python
from liquidation_utils import (
    ...
)
```
to:
```python
from sim.liquidation.liquidation_utils import (
    ...
)
```
(Preserve the parenthesised name list verbatim.)

Change the line-26 block from:
```python
from rolldown_utils import (
    ...
)
```
to:
```python
from sim.rolldown.rolldown_utils import (
    ...
)
```

- [ ] **Step 3: `sim/rolldown/bitmor_rolldown_mc.py` — argparse defaults**

Change line 511:
```python
p.add_argument("--surface", default="btc_iv_surface_svi.csv",
```
to:
```python
p.add_argument("--surface", default="data/btc_iv_surface_svi.csv",
```

Change line 513:
```python
p.add_argument("--price", default="BTCUSDT_1h.csv",
```
to:
```python
p.add_argument("--price", default="data/BTCUSDT_1h.csv",
```

- [ ] **Step 4: `sim/rolldown/bitmor_rolldown_mc.py` — output paths**

Lines ~568–586 contain six `f"result/rolldown_tier{N}_{today}.csv"` strings. Replace `result/` with `results/` in each. Use `replace_all=true` on the substring `"result/rolldown_tier` → `"results/rolldown_tier`.

Line 590:
```python
dashboard = "bitmor-dashboard.html"
```
to:
```python
dashboard = "dashboard/bitmor-dashboard.html"
```

Add a `os.makedirs("results", exist_ok=True)` call near the top of the function that writes those CSVs (before the first `save_tier_csv`). Inspect the function to find the right spot — likely just after `today = ...` is computed.

- [ ] **Step 5: `sim/ivsurface/btc_iv.py`**

Line 34:
```python
CSV_FILE         = "btc_iv_surface2.csv"
```
to:
```python
CSV_FILE         = "data/btc_iv_surface2.csv"
```

Line 35:
```python
PNG_DIR          = pathlib.Path("surfaces")
```
to:
```python
PNG_DIR          = pathlib.Path("results/surfaces")
```

Line 40 — `PNG_DIR.mkdir(exist_ok=True)` becomes `PNG_DIR.mkdir(parents=True, exist_ok=True)` (since the parent `results/` may not exist yet).

Line 257 area — the file does `df.to_csv(CSV_FILE, ...)`. Add a mkdir guard immediately above:
```python
pathlib.Path(CSV_FILE).parent.mkdir(parents=True, exist_ok=True)
df.to_csv(CSV_FILE, mode=mode, header=header, index=False, float_format="%.6f")
```

- [ ] **Step 6: `sim/ivsurface/iv_surface_svi.py`**

Lines 238–241 — argparse defaults:

```python
p.add_argument("--opt", default="data/btc_iv_surface2.csv",  help="Input: options CSV file")
p.add_argument("--px",  default="data/BTCUSDT_1h.csv",       help="Input: spot CSV file")
p.add_argument("--out_param", default="data/btc_svi_params.csv",      help="Output: SVI parameters per day")
p.add_argument("--out_surf",  default="data/btc_iv_surface_svi.csv", help="Output: synthetic IV surface grid")
```

Line 313 area — `params.to_csv(cfg.out_param, index=False)`. Add a mkdir guard immediately above:
```python
Path(cfg.out_param).parent.mkdir(parents=True, exist_ok=True)
params.to_csv(cfg.out_param, index=False)
```

Line 350 area — `surf_df.to_csv(cfg.out_surf, ...)`. Same guard:
```python
Path(cfg.out_surf).parent.mkdir(parents=True, exist_ok=True)
surf_df.to_csv(cfg.out_surf, index=False, float_format="%.6f")
```

- [ ] **Step 7: `sim/backtest/historical_backtest.py`**

Replace lines 24–28 (the imports from `config` / `liquidation_waterfall` / `rolldown_utils` / `liquidation_utils`):

```python
from sim.shared import config
from sim.liquidation.liquidation_waterfall import compute_waterfall
from sim.rolldown.rolldown_utils import lookup_iv, snap_to_strike, apply_slippage
from sim.liquidation.liquidation_utils import (
    ...
)
```

Preserve the multi-line import name list inside the parentheses verbatim.

- [ ] **Step 8: `sim/backtest/backtest_report.py`**

Lines 15–16:
```python
import config
from liquidation_utils import load_price
```
to:
```python
from sim.shared import config
from sim.liquidation.liquidation_utils import load_price
```

- [ ] **Step 9: `sim/backtest/run_backtest.py` — imports**

Lines 16–18:
```python
import config
from historical_backtest import run_backtest
from backtest_report import save_backtest_results
```
to:
```python
from sim.shared import config
from sim.backtest.historical_backtest import run_backtest
from sim.backtest.backtest_report import save_backtest_results
```

- [ ] **Step 10: `sim/backtest/run_backtest.py` — embed-script invocation**

Look for the block around lines 36–40 that calls `subprocess` against `embed_csv_to_dashboard.py`. Replace the whole block with an in-process import + call (cleaner) OR a `subprocess` call to `python -m dashboard.embed_csv_to_dashboard`.

If currently:
```python
fragment_path = config.RESULTS_DIR / "backtest" / "backtest_tab_fragment.html"
embed_script  = config.INSURANCE_COST_DIR / "embed_csv_to_dashboard.py"
dashboard     = config.INSURANCE_COST_DIR / "bitmor-dashboard.html"
subprocess.run([sys.executable, str(embed_script), "--backtest", str(fragment_path), "--dashboard", str(dashboard)], check=True)
```

Replace with:
```python
fragment_path = config.RESULTS_DIR / "backtest" / "backtest_tab_fragment.html"
subprocess.run(
    [sys.executable, "-m", "dashboard.embed_csv_to_dashboard",
     "--backtest", str(fragment_path),
     "--dashboard", str(config.DASHBOARD_HTML)],
    check=True,
    cwd=str(config.REPO_ROOT),   # ensures `python -m dashboard....` resolves
)
```

(If the original block has different exact lines or includes other args, preserve them — only change the script path mechanism and `INSURANCE_COST_DIR` references.)

- [ ] **Step 11: `dashboard/embed_csv_to_dashboard.py`**

Line ~46:
```python
p.add_argument("--dashboard", default="bitmor-dashboard.html")
```
to:
```python
p.add_argument("--dashboard", default="dashboard/bitmor-dashboard.html")
```

Line ~57 area:
```python
result_dir = Path("result")
```
to:
```python
result_dir = Path("results")
```

### 4d — Inject repo root into pytest's `sys.path`

Without this, `pytest tests/` may fail with `ModuleNotFoundError: No module named 'sim'` because pytest's rootdir detection can land at `tests/`, not the repo root.

- [ ] **Step 0: Prepend a path-injection block to `tests/conftest.py`**

Open `tests/conftest.py`. The existing file has fixtures starting at line 1 with `import numpy as np`. Add this block at the very top (lines 1–4 become):

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_surface():
    ...
```

The `sys.path.insert` adds the repo root (parent of `tests/`) so `from sim.X.Y import Z` resolves from within tests. The existing fixture code below it stays untouched.

### 4e — Rewrite test imports

- [ ] **Step 1: `tests/rolldown/test_rolldown_mc.py`**

Replace every occurrence:
- `from bitmor_rolldown_mc import` → `from sim.rolldown.bitmor_rolldown_mc import`
- `from liquidation_utils import` → `from sim.liquidation.liquidation_utils import`

(There are 6 lines in `test_rolldown_mc.py` doing in-test imports — lines 4, 105, 137, 176, 218, 250 plus the line 328 `liquidation_utils` import.)

- [ ] **Step 2: `tests/rolldown/test_rolldown_utils.py`**

Replace every occurrence:
- `from rolldown_utils import` → `from sim.rolldown.rolldown_utils import`
- `from btc_iv import` → `from sim.ivsurface.btc_iv import`

(Lines 5, 34, 74, 151, 185, 247, 271 — verify with `grep -nE "^from " tests/rolldown/test_rolldown_utils.py` after editing.)

- [ ] **Step 3: `tests/ivsurface/test_btc_iv.py`**

Line 7:
```python
from btc_iv import (
```
to:
```python
from sim.ivsurface.btc_iv import (
```

- [ ] **Step 4: `tests/ivsurface/test_iv_surface_svi.py`**

Line 6:
```python
from iv_surface_svi import assign_tenor_bucket, calibrate_svi, TENOR_BUCKETS
```
to:
```python
from sim.ivsurface.iv_surface_svi import assign_tenor_bucket, calibrate_svi, TENOR_BUCKETS
```

- [ ] **Step 5: `tests/backtest/test_waterfall.py`**

Line 3:
```python
from liquidation_waterfall import compute_waterfall, WaterfallResult
```
to:
```python
from sim.liquidation.liquidation_waterfall import compute_waterfall, WaterfallResult
```

- [ ] **Step 6: `tests/test_integration.py`**

```bash
grep -nE "^from " tests/test_integration.py
```

For every project import (e.g. `from rolldown_utils import X`, `from bitmor_rolldown_mc import Y`), prefix with `sim.<subsystem>.`. Standard-library and third-party imports (`pandas`, `pytest`, `pathlib`) stay unchanged.

### 4f — Verify imports & run tests

- [ ] **Step 1: Smoke-test every entry-point module imports**

```bash
cd "/mnt/c/Users/suryansh/2025 projects/Monte carlo for insurance cost"
python -c "import sim.rolldown.bitmor_rolldown_mc"
python -c "import sim.rolldown.rolldown_utils"
python -c "import sim.ivsurface.btc_iv"
python -c "import sim.ivsurface.iv_surface_svi"
python -c "import sim.liquidation.liquidation_utils"
python -c "import sim.liquidation.liquidation_waterfall"
python -c "import sim.backtest.historical_backtest"
python -c "import sim.backtest.backtest_report"
python -c "import sim.backtest.run_backtest"
python -c "import sim.shared.config"
python -c "import dashboard.embed_csv_to_dashboard"
```

Expected: each command exits 0 with no output. Any `ImportError` or `ModuleNotFoundError` flags an import you missed — go back to 4c/4d and fix it.

- [ ] **Step 2: Run the test suite**

```bash
pytest tests/ --tb=short -q
```

Expected: same number of passing tests as `/tmp/baseline-pytest.txt` minus the 5–6 tests that were in `test_price_paths.py`. No new failures.

If a test fails: read the traceback, compare to the import-rewrite table, fix, re-run.

If you see `ModuleNotFoundError: No module named 'sim'` despite the conftest fix, double-check that `tests/conftest.py` step 4d landed and that you're running pytest from the repo root.

- [ ] **Step 3: Commit**

```bash
git add sim/ dashboard/ tests/
git status --short
```

Expected: many `M` (modified) entries plus `A` for the new `__init__.py` files.

```bash
git commit -m "$(cat <<'EOF'
refactor: rewrite imports to absolute sim.* paths, fix data/results paths

- Add empty __init__.py per sim subpackage and per tests subpackage so
  `python -m` and pytest discovery both work without sys.path hacks.
- Rewrite every flat import (from rolldown_utils import X, etc.) to its
  absolute counterpart (from sim.rolldown.rolldown_utils import X).
- sim/shared/config.py drops the cross-repo INSURANCE_COST_DIR bridge
  in favour of REPO_ROOT, repoints all CSV paths to data/, adds
  DASHBOARD_HTML.
- Hardcoded simulator I/O paths now read from data/ and write to
  results/ (with mkdir guards). Embed script defaults updated.
- run_backtest.py invokes the embed step via `python -m
  dashboard.embed_csv_to_dashboard` instead of subprocess against an
  absolute file path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Update Vercel & Ignore Files

**Files:**
- Modify: `vercel.json`
- Modify: `.vercelignore`
- Modify: `.gitignore`

- [ ] **Step 1: Update `vercel.json`**

Replace the entire contents with:

```json
{
  "buildCommand": "",
  "outputDirectory": ".",
  "rewrites": [
    { "source": "/", "destination": "/dashboard/bitmor-dashboard.html" }
  ]
}
```

The only change is the rewrite destination from `/bitmor-dashboard.html` to `/dashboard/bitmor-dashboard.html`.

- [ ] **Step 2: Update `.vercelignore`**

Replace the entire contents with:

```
# Source code (not deployed; only the dashboard HTML is)
sim/
tests/
docs/
*.py
__pycache__/

# Data + outputs (large, not needed for static deploy)
data/
results/
*.csv
*.png

# Python tooling artefacts
.pytest_cache/
.gitignore
*.pdf
```

- [ ] **Step 3: Update `.gitignore`**

Replace the entire contents with:

```
# Python
__pycache__/
*.pyc
.pytest_cache/

# Vercel
.vercel/

# Local data (large, not under version control)
data/*.csv
*.csv

# Results (regeneratable)
results/

# Old name retained for back-compat (defensive)
result/
surfaces/

# IDE / OS
.DS_Store
.idea/
.vscode/
```

- [ ] **Step 4: Verify Vercel build picks up the new path locally**

```bash
# If you have vercel CLI installed:
npx vercel build --yes 2>&1 | tail -20
```

Expected: build succeeds; `.vercel/output/...` reflects the new dashboard path. If `vercel` isn't installed, skip — the production deploy in Task 7 will catch any issue.

- [ ] **Step 5: Open the dashboard locally**

Open `dashboard/bitmor-dashboard.html` in a browser. Walk through every tab from the baseline screenshots in pre-flight Step 3. **Every tab must render the same as before.** If anything is broken: most likely a relative path inside the HTML is now broken because the HTML moved into `dashboard/`. The HTML embeds CSVs as inline JS strings (the embed script) and shouldn't load anything from disk at render time — but if the dashboard references `./surfaces/foo.png` or `./result/foo.csv`, those are now broken.

If broken: investigate, fix in-place in the HTML, include the fix in this commit.

- [ ] **Step 6: Commit**

```bash
git add vercel.json .vercelignore .gitignore
git commit -m "$(cat <<'EOF'
chore: update vercel.json, .vercelignore, .gitignore for new layout

- vercel.json rewrite: / → /dashboard/bitmor-dashboard.html
- .vercelignore extended for sim/, tests/, docs/, data/, results/
- .gitignore extended for data/*.csv, results/

Verified: dashboard/bitmor-dashboard.html still renders all tabs locally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: README, requirements.txt, Merge docs/plans/

**Files:**
- Create: `README.md` at repo root
- Create: `requirements.txt` at repo root

`docs/plans/` already merged in Task 2; nothing more to do there beyond a sanity check.

- [ ] **Step 1: Generate `requirements.txt`**

The simplest reliable approach is to enumerate the third-party imports already in the codebase. Run:

```bash
grep -hE "^(import|from) " sim/**/*.py dashboard/*.py tests/**/*.py 2>/dev/null \
  | grep -vE "from (sim|tests|dashboard|__future__|typing|pathlib|argparse|logging|re|sys|os|datetime|dataclasses|csv|math|time|subprocess|unittest)" \
  | grep -vE "^import (sys|os|re|argparse|logging|pathlib|datetime|csv|math|time|subprocess|unittest|json|typing|dataclasses)" \
  | sort -u
```

Expected (approximately): imports from `numpy`, `pandas`, `scipy`, `matplotlib`, `requests`, `joblib`, `pytest`. Confirm the list visually.

Write `requirements.txt`:

```
numpy>=1.26
pandas>=2.0
scipy>=1.11
matplotlib>=3.8
requests>=2.31
joblib>=1.3
pytest>=7.4
```

(Pin loosely with `>=` minor-version bounds. If a dependency turns out missing in Task 7's smoke test, add it.)

- [ ] **Step 2: Write `README.md` at repo root**

Write `README.md` exactly as below. The architecture diagram and run table are concrete; no placeholder content.

```markdown
# Bitmor — BTC-Collateralised Lending Simulator & Dashboard

End-to-end simulation stack for Bitmor's BTC-collateralised lending product:
implied-volatility surface fitting, Monte Carlo simulation of put-rolldown
hedge programs, historical backtests of liquidation behaviour, and an
interactive dashboard deployed to Vercel.

## Architecture

\`\`\`
                   ┌──────────────────────┐
                   │ sim/ivsurface/       │  raw IV options + spot prices →
                   │ btc_iv, iv_surface_  │  per-day SVI parameters →
                   │ svi                  │  synthetic IV surface grid
                   └──────────┬───────────┘
                              │ data/btc_iv_surface_svi.csv
                              ▼
        ┌─────────────────────┼──────────────────────┐
        │                     │                      │
        ▼                     ▼                      ▼
┌──────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ sim/rolldown │    │ sim/backtest     │    │ sim/liquidation │
│ Monte Carlo  │    │ Historical       │    │ Waterfall       │
│ put rolldown │    │ replay backtest  │    │ math (shared)   │
└──────┬───────┘    └─────────┬────────┘    └────────┬────────┘
       │                      │                      │
       └─────────────┬────────┴──────────────────────┘
                     │ results/*.csv
                     ▼
              ┌────────────────┐
              │ dashboard/     │  Vercel-deployed static
              │ bitmor-        │  HTML with embedded CSVs
              │ dashboard.html │
              └────────────────┘
\`\`\`

## Folder Layout

\`\`\`
.
├── dashboard/      # Vercel-deployed HTML + embed pipeline
├── sim/
│   ├── rolldown/   # Put-rolldown Monte Carlo simulator
│   ├── backtest/   # Historical replay backtest
│   ├── ivsurface/  # IV options scrape + SVI surface fitting
│   ├── liquidation/ # Liquidation waterfall + shared option math
│   └── shared/     # config.py (paths, loan parameters, MC settings)
├── data/           # Raw inputs (gitignored): BTCUSDT_1h.csv, btc_iv_surface*.csv
├── results/        # Simulation outputs (gitignored)
├── tests/          # pytest suite, mirrors sim/ layout
├── docs/
│   ├── plans/      # Per-feature design + implementation docs
│   └── superpowers/specs/   # Cross-cutting design specs
├── vercel.json
└── requirements.txt
\`\`\`

## Setup

Requires Python 3.11+.

\`\`\`bash
python -m venv venv
source venv/bin/activate    # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
\`\`\`

The simulators expect input CSVs under `data/`. Required files:

- `data/BTCUSDT_1h.csv` — Binance 1h spot price history
- `data/btc_iv_surface2.csv` — Deribit options snapshots (regenerate via `sim.ivsurface.btc_iv`)
- `data/btc_iv_surface_svi.csv` — fitted SVI surface (regenerate via `sim.ivsurface.iv_surface_svi`)

## Running Individual Simulators

All commands run from the repo root.

| Simulator | Command | Reads | Writes |
|---|---|---|---|
| Rolldown MC | `python -m sim.rolldown.bitmor_rolldown_mc` | `data/btc_iv_surface_svi.csv`, `data/BTCUSDT_1h.csv` | `results/rolldown_tier{1,2,3}*.csv` |
| Historical backtest | `python -m sim.backtest.run_backtest` | `data/*` | `results/backtest/*.csv`, `results/backtest/backtest_report.html` |
| IV options scrape | `python -m sim.ivsurface.btc_iv` | (Deribit API) | `data/btc_iv_surface2.csv`, `results/surfaces/*.png` |
| SVI fitting | `python -m sim.ivsurface.iv_surface_svi` | `data/btc_iv_surface2.csv`, `data/BTCUSDT_1h.csv` | `data/btc_svi_params.csv`, `data/btc_iv_surface_svi.csv` |
| Liquidation waterfall (standalone) | `python -m sim.liquidation.liquidation_waterfall` | (CLI args) | stdout |

## Rebuilding the Dashboard

After running simulators, embed their outputs into the dashboard HTML:

\`\`\`bash
python -m dashboard.embed_csv_to_dashboard --date YYYYMMDD \\
       --backtest results/backtest/backtest_tab_fragment.html
\`\`\`

Then preview locally: open `dashboard/bitmor-dashboard.html` in a browser.

## Deploying

\`\`\`bash
npx vercel --yes --prod
\`\`\`

Vercel deploys `dashboard/bitmor-dashboard.html` and rewrites `/` to it. Everything outside `dashboard/` is excluded by `.vercelignore`.

## Running Tests

\`\`\`bash
pytest tests/
\`\`\`

`tests/conftest.py` handles path setup; no extra configuration needed.

## Conventions

- **Relocate, don't rename.** Each `sim/<subsystem>/<file>.py` keeps its original basename.
- **Inputs in `data/`, outputs in `results/`** — both gitignored.
- **One package per subsystem.** Empty `__init__.py` files mark them; no `pyproject.toml`.
- **Design docs in `docs/plans/`** — dated `YYYY-MM-DD-<topic>-design.md` and `-impl.md`.
\`\`\`
```

(The `\`\`\`` escapes are because this Markdown is inside a Markdown code block. Strip the backslashes when actually writing the file — i.e. the README's own code fences are unescaped.)

- [ ] **Step 3: Verify `docs/plans/` is intact**

```bash
ls docs/plans/ | sort
```

Expected: ten dated plan files — five from the original repo (2026-03-30 through 2026-04-01) and five copied in Task 2 (2026-04-04 through 2026-04-06).

- [ ] **Step 4: Commit**

```bash
git add README.md requirements.txt docs/plans/
git commit -m "$(cat <<'EOF'
docs: add README.md and requirements.txt; consolidate docs/plans

- README documents architecture, folder layout, per-simulator run
  commands, dashboard rebuild, deploy, and conventions.
- requirements.txt enumerates third-party deps actually imported by
  the codebase (numpy, pandas, scipy, matplotlib, requests, joblib,
  pytest).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Final Validation Gate & Branch Merge

**Files:** none modified — pure verification + git workflow.

- [ ] **Step 1: Full test run**

```bash
pytest tests/ --tb=short -v
```

Expected: green. Compare pass count to `/tmp/baseline-pytest.txt` minus the dropped `test_price_paths.py` (~5 tests). No new failures.

- [ ] **Step 2: Smoke-test every entry-point module starts cleanly**

```bash
for mod in sim.rolldown.bitmor_rolldown_mc sim.backtest.run_backtest sim.backtest.historical_backtest sim.ivsurface.btc_iv sim.ivsurface.iv_surface_svi sim.liquidation.liquidation_waterfall dashboard.embed_csv_to_dashboard; do
  echo "=== $mod ==="
  python -c "import importlib; importlib.import_module('$mod'); print('OK')"
done
```

Expected: each module prints `OK`. An ImportError flags a missed import refactor — fix and add a follow-up commit.

- [ ] **Step 3: Dashboard render check**

Open `dashboard/bitmor-dashboard.html` in a browser. Walk through every tab from the baseline screenshots. Every tab must render identically to baseline. Open the browser console — no new errors.

- [ ] **Step 4: Vercel build (if CLI installed)**

```bash
npx vercel build --yes 2>&1 | tail -10
```

Expected: build success; `.vercel/output/` produced. Skip if Vercel CLI is unavailable; deploy in Step 6 will surface any issue.

- [ ] **Step 5: Confirm clean git state**

```bash
git status
git log --oneline dashboard-rehaul..HEAD
```

Expected: working tree clean; six new commits on `consolidation` since the branch point.

- [ ] **Step 6: Merge to `dashboard-rehaul`**

```bash
git checkout dashboard-rehaul
git merge --no-ff consolidation -m "$(cat <<'EOF'
Consolidate default-and-liquidation-mc into this repo

Six-commit consolidation: working-tree cleanup, file copy from the
other repo, relocation into sim/ + dashboard/ + data/ + results/
layout, import refactor with absolute sim.* paths, vercel/.gitignore
update, README + requirements.txt.

Validation: pytest green, every sim entry point imports clean,
dashboard renders unchanged, vercel build succeeds.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git log --oneline -10
```

- [ ] **Step 7: Deploy preview to Vercel (optional, recommended)**

```bash
npx vercel --yes
```

Open the preview URL. Walk through every tab. Confirm parity with the local render. Only after that:

```bash
npx vercel --yes --prod
```

- [ ] **Step 8: Delete the other repo (only after preview deploy succeeds)**

The user owns this step — don't run it autonomously. Suggest:

> "The consolidation is verified end-to-end (tests green, dashboard renders, prod deploy live). The `default-and-liquidation-mc/` repo is now redundant. You can delete it with `rm -rf "/mnt/c/Users/suryansh/2025 projects/default-and-liquidation-mc"` whenever you're ready."

---

## Summary

| # | Commit | Validation |
|---|---|---|
| 1 | `chore: clean up working tree before consolidation` | git status clean |
| 2 | `chore: copy default-and-liquidation-mc files into repo root` | files exist + tracked |
| 3 | `refactor: relocate files into sim/, dashboard/, data/, tests/ layout` | git mv shows rename detection |
| 4 | `refactor: rewrite imports to absolute sim.* paths, fix data/results paths` | every entry point imports + pytest green |
| 5 | `chore: update vercel.json, .vercelignore, .gitignore for new layout` | dashboard renders locally |
| 6 | `docs: add README.md and requirements.txt; consolidate docs/plans` | docs sanity check |
| 7 | (merge to dashboard-rehaul) | full validation gate + prod deploy |

**Spec deviations:**
- Dropped `tests/test_price_paths.py` (not anticipated in spec — its dependency `price_paths.py` only exists in the abandoned `old/` folder, no live code references it).
