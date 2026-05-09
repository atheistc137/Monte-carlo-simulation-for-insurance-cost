#!/usr/bin/env python3
"""
Entry point: run the historical backtest and produce reports.

Usage:
    python run_backtest.py               # full backtest (~1,460 loans)
    python run_backtest.py --limit 50    # quick test (first 50 loans only)
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys

import config
from historical_backtest import run_backtest
from backtest_report import save_backtest_results

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("run_backtest")


def main():
    parser = argparse.ArgumentParser("Historical Backtest — Coverage Analysis")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit to first N origination dates (0 = all)")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip embedding into the Bitmor dashboard")
    args = parser.parse_args()

    df = run_backtest(limit=args.limit)
    save_backtest_results(df)

    # Embed into Bitmor dashboard
    if not args.no_embed:
        fragment_path = config.RESULTS_DIR / "backtest" / "backtest_tab_fragment.html"
        embed_script = config.INSURANCE_COST_DIR / "embed_csv_to_dashboard.py"
        dashboard = config.INSURANCE_COST_DIR / "bitmor-dashboard.html"

        if fragment_path.exists() and embed_script.exists() and dashboard.exists():
            log.info("Embedding backtest into dashboard: %s", dashboard)
            subprocess.run([
                sys.executable, str(embed_script),
                "--backtest", str(fragment_path),
                "--dashboard", str(dashboard),
            ], check=True)
        else:
            log.warning("Skipping dashboard embed — missing files")


if __name__ == "__main__":
    main()
