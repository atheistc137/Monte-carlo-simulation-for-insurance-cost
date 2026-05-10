# Bitmor — BTC-Collateralised Lending Simulator & Dashboard

End-to-end simulation stack for Bitmor's BTC-collateralised lending product:
implied-volatility surface fitting, Monte Carlo simulation of put-rolldown
hedge programs, historical backtests of liquidation behaviour, and an
interactive dashboard deployed to Vercel.

## Architecture

```
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
```

## Folder Layout

```
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
```

## Setup

Requires Python 3.11+.

```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

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

```bash
python -m dashboard.embed_csv_to_dashboard --date YYYYMMDD \
       --backtest results/backtest/backtest_tab_fragment.html
```

Then preview locally: open `dashboard/bitmor-dashboard.html` in a browser.

## Deploying

```bash
npx vercel --yes --prod
```

Vercel deploys `dashboard/bitmor-dashboard.html` and rewrites `/` to it. Everything outside `dashboard/` is excluded by `.vercelignore`.

## Running Tests

```bash
pytest tests/
```

`tests/conftest.py` handles path setup; no extra configuration needed.

## Conventions

- **Relocate, don't rename.** Each `sim/<subsystem>/<file>.py` keeps its original basename.
- **Inputs in `data/`, outputs in `results/`** — both gitignored.
- **One package per subsystem.** Empty `__init__.py` files mark them; no `pyproject.toml`.
- **Design docs in `docs/plans/`** — dated `YYYY-MM-DD-<topic>-design.md` and `-impl.md`.
