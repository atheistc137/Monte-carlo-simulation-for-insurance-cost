# Repo Consolidation & Restructure — Design

**Date:** 2026-05-09
**Status:** Approved (pending spec review)
**Branch target:** `consolidation` off `dashboard-rehaul`

## Goal

Merge `2025 projects/default-and-liquidation-mc/` into `2025 projects/Monte carlo for insurance cost/` and reorganise the combined codebase so it can be pushed as a single coherent project. The consolidated repo must:

1. Allow each individual simulator to be run standalone with one command.
2. Ship a README that explains the project, layout, and every workflow.
3. Keep the existing Vercel deploy of `bitmor-dashboard.html` working without interruption.

## Success Criteria

- `pytest tests/` is green.
- Each `python -m sim.<subsystem>.<module>` command starts without `ImportError`.
- `dashboard/bitmor-dashboard.html` renders correctly when opened locally.
- `npx vercel build` (or a preview deploy) succeeds against the new layout.
- Repo root contains no orphaned simulator `.py` files; everything lives under `sim/`, `dashboard/`, `tests/`, `data/`, `results/`, `docs/`.

## Sources

| Source repo | Branch | Treatment |
|---|---|---|
| `Monte carlo for insurance cost/` | `dashboard-rehaul` | Stays put; receives all changes. Existing git history preserved. |
| `default-and-liquidation-mc/` | `master` | Working-tree copy (committed + uncommitted/untracked). Git history **abandoned**. The other repo can be deleted after consolidation merges. |

The other repo has substantial uncommitted work (`backtest_report.py`, `historical_backtest.py`, `run_backtest.py`, `config.py`, `liquidation_waterfall.py`, three new design docs under `docs/plans/`, `results/backtest/` outputs). Plain working-tree copy captures all of it.

## Target Folder Structure

```
bitmor/
├── dashboard/
│   ├── bitmor-dashboard.html      ← Vercel target (rewrite updated to /dashboard/...)
│   └── embed_csv_to_dashboard.py
├── sim/
│   ├── rolldown/                  ← bitmor_rolldown_mc.py, rolldown_utils.py
│   ├── backtest/                  ← historical_backtest.py, backtest_report.py, run_backtest.py
│   ├── ivsurface/                 ← btc_iv.py, iv_surface_svi.py
│   ├── liquidation/               ← liquidation_utils.py, liquidation_waterfall.py
│   └── shared/                    ← config.py
├── data/                          ← raw input CSVs (gitignored)
├── results/                       ← simulation outputs (gitignored)
├── tests/
│   ├── conftest.py
│   ├── test_integration.py
│   ├── rolldown/                  ← test_rolldown_mc.py, test_rolldown_utils.py
│   ├── ivsurface/                 ← test_btc_iv.py, test_iv_surface_svi.py
│   └── backtest/                  ← test_price_paths.py, test_waterfall.py
├── docs/
│   ├── plans/                     ← merged design + impl docs from both repos
│   └── superpowers/specs/
├── vercel.json                    ← rewrite updated
├── .vercelignore                  ← extended for new layout
├── .gitignore                     ← extended for data/, results/
└── README.md                      ← new
```

`old/` directories from both source repos are dropped entirely. `archive/` is not created. Regenerable artefacts (`__pycache__/`, `.pytest_cache/`) are excluded from the move.

## File Mapping

✓ = from `Monte carlo for insurance cost/`, ◆ = from `default-and-liquidation-mc/`.

| New path | Source |
|---|---|
| `dashboard/bitmor-dashboard.html` | ✓ `bitmor-dashboard.html` |
| `dashboard/embed_csv_to_dashboard.py` | ✓ `embed_csv_to_dashboard.py` |
| `sim/rolldown/bitmor_rolldown_mc.py` | ✓ `bitmor_rolldown_mc.py` |
| `sim/rolldown/rolldown_utils.py` | ✓ `rolldown_utils.py` |
| `sim/ivsurface/btc_iv.py` | ✓ `btc_iv.py` |
| `sim/ivsurface/iv_surface_svi.py` | ✓ `iv_surface_svi.py` |
| `sim/liquidation/liquidation_utils.py` | ✓ `liquidation_utils.py` |
| `sim/liquidation/liquidation_waterfall.py` | ◆ `liquidation_waterfall.py` |
| `sim/backtest/historical_backtest.py` | ◆ `historical_backtest.py` |
| `sim/backtest/backtest_report.py` | ◆ `backtest_report.py` |
| `sim/backtest/run_backtest.py` | ◆ `run_backtest.py` |
| `sim/shared/config.py` | ◆ `config.py` |
| `tests/conftest.py`, `tests/test_integration.py` | ✓ (stay at top-level of `tests/`) |
| `tests/rolldown/test_rolldown_mc.py`, `tests/rolldown/test_rolldown_utils.py` | ✓ |
| `tests/ivsurface/test_btc_iv.py`, `tests/ivsurface/test_iv_surface_svi.py` | ✓ |
| `tests/backtest/test_price_paths.py`, `tests/backtest/test_waterfall.py` | ◆ |
| `docs/plans/2026-03-30-*.md`, `2026-03-31-*.md`, `2026-04-01-*.md` | ✓ |
| `docs/plans/2026-04-04-*.md`, `2026-04-05-*.md`, `2026-04-06-*.md` | ◆ |
| `data/BTCUSDT_1h.csv`, `data/btc_iv_surface*.csv`, `data/btc_svi_params.csv` | ✓ (gitignored) |
| `results/backtest/*` | ◆ (gitignored) |
| `vercel.json`, `.vercelignore`, `.gitignore` | ✓ (edited in place) |

No filename collisions detected between the two source repos.

## Naming Policy

**Relocate, don't rename.** Every file keeps its current basename; only its parent directory changes. New files added during consolidation: empty `__init__.py` per package, `README.md` at root, `requirements.txt` at root (generated from current imports). No file is renamed.

Reason: minimises import-refactor blast radius, preserves filename recognition, lowers risk of breaking the dashboard pipeline.

## Imports & Runnability

Each `sim/<subsystem>/`, `sim/shared/`, `dashboard/`, and each `tests/<subsystem>/` directory becomes a Python package via an empty `__init__.py`. No `pyproject.toml`, no editable install — Python auto-adds the cwd to `sys.path` when invoked via `python -m` from the repo root.

**Import rewrite rule:** every flat import (`from rolldown_utils import X`) becomes an absolute package import (`from sim.rolldown.rolldown_utils import X`). All such rewrites land in a single commit.

**Canonical run commands** (all from repo root):

```bash
# Simulators
python -m sim.rolldown.bitmor_rolldown_mc
python -m sim.backtest.run_backtest
python -m sim.backtest.historical_backtest
python -m sim.ivsurface.btc_iv
python -m sim.ivsurface.iv_surface_svi
python -m sim.liquidation.liquidation_waterfall

# Dashboard rebuild
python -m dashboard.embed_csv_to_dashboard

# Tests
pytest tests/
```

## Path-Handling Rule

Every hardcoded input/output path inside the simulators is rewritten in the import-refactor commit:

- Input CSVs → `data/<filename>.csv`
- Outputs → `results/<filename>.csv` (subfoldered if the simulator already does so, e.g. `results/backtest/`)

Both directories are gitignored. The simulators must create `results/<subdir>/` if it doesn't exist (`os.makedirs(..., exist_ok=True)` or equivalent).

## Vercel Continuity

Three deploy-config edits, all in commit 5:

1. `vercel.json` rewrite: `/` → `/dashboard/bitmor-dashboard.html` (was `/bitmor-dashboard.html`).
2. `.vercelignore` extended: add `sim/`, `tests/`, `docs/`, `data/`, `results/` (already ignores `*.py`).
3. Local verification: open `dashboard/bitmor-dashboard.html` in a browser and confirm every tab renders **before** the commit ships. `npx vercel build` runs as a final check.

## README Structure

`README.md` at repo root, sections in this order:

1. **What this is** — one paragraph: BTC-collateralised lending simulator + Vercel dashboard.
2. **Architecture** — ASCII diagram: IV-surface pipeline → rolldown MC + historical backtest → liquidation waterfall → dashboard.
3. **Folder layout** — annotated tree, one line per top-level directory.
4. **Setup** — Python version, `pip install -r requirements.txt`.
5. **Running individual simulators** — table with one row per `python -m …` command, listing inputs (`data/…`) and outputs (`results/…`).
6. **Rebuilding the dashboard** — `python -m dashboard.embed_csv_to_dashboard`, plus how to preview locally.
7. **Deploying** — `npx vercel --yes --prod`.
8. **Tests** — `pytest tests/`.
9. **Repo conventions** — relocate-don't-rename, gitignored data/results, design docs in `docs/plans/`.

`requirements.txt` is generated by inspecting current imports (one-time chore during the README commit). No `pyproject.toml` is added.

## Validation Gate

Before any commit ships, the following must pass in order. If any step fails, fix it inline before the next commit — do not paper over.

1. `pytest tests/` → green (all existing test files).
2. Each `python -m sim.X.Y` and `python -m dashboard.Y` command starts without `ImportError` (smoke test — does not need to complete a full run).
3. `dashboard/bitmor-dashboard.html` opens locally and every tab that worked pre-move still renders.
4. `npx vercel build` succeeds against the new layout.

## Commit Strategy

A new branch `consolidation` off `dashboard-rehaul`, six commits:

| # | Commit message | Scope |
|---|---|---|
| 1 | `chore: clean up working tree before consolidation` | Stage and commit the existing `old/` deletions already in `dashboard-rehaul`'s working tree. |
| 2 | `chore: copy default-and-liquidation-mc files into repo root` | Working-tree copy of the other repo into the current repo root, no relocation yet. Isolated diff. |
| 3 | `refactor: relocate files into sim/, dashboard/, data/, tests/` | `git mv` only. Git rename detection preserves blame. |
| 4 | `refactor: rewrite imports to absolute sim.* paths` | Add `__init__.py` files, rewrite imports, update hardcoded CSV paths to `data/` and `results/`. |
| 5 | `chore: update vercel.json and .vercelignore for new layout` | Deploy-config in isolation — easy to revert if Vercel breaks. |
| 6 | `docs: add README.md, requirements.txt, merge docs/plans/` | Documentation layer last. |

After commit 6, run the validation gate end-to-end. Then merge `consolidation` into `dashboard-rehaul` (or open a PR — user's call).

## Out of Scope

- Renaming any existing source file.
- Preserving git history from `default-and-liquidation-mc/`.
- Preserving either `old/` directory.
- Adding `pyproject.toml`, `setup.py`, `Makefile`, or any other tooling beyond `requirements.txt`.
- Any new feature work; this is pure restructure.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Hidden hardcoded path I miss in the import-refactor pass | Validation gate step 2 (smoke test every entry point). Run before commit 5 ships. |
| Vercel rewrite mismatch breaks the live dashboard | Commit 5 is isolated; if `vercel build` fails, revert commit 5 only. |
| Test collection misses the new `tests/<subsystem>/` directories | Verify `tests/<subsystem>/__init__.py` exists in commit 4; confirm pytest discovery in commit 6's validation pass. |
| Uncommitted work in the other repo gets lost during copy | Plain working-tree copy captures everything. No backup commit needed in the source repo since we're abandoning its history anyway. |

## Open Decisions Resolved During Brainstorming

- **Git history strategy:** plain copy, abandon other repo's history.
- **Folder taxonomy:** hybrid layout (sim/ subsystems + dashboard/).
- **Archive folders:** drop both `old/` directories entirely.
- **Heavy CSVs:** moved to `data/` (gitignored).
- **Other repo's uncommitted work:** captured by plain working-tree copy; no backup snapshot needed.
