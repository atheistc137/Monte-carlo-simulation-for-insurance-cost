#!/usr/bin/env python3
"""Embed rolldown CSV results into bitmor-dashboard.html.

Replaces the inline JS string constants (TIER1_CSV, TIER2_CSV, TIER3_CSV)
and adds TIER1_DETAIL_CSV, TIER3_DETAIL_CSV for per-month roll data.
"""
import re
import sys
from pathlib import Path


def read_csv(path: str) -> str:
    """Read CSV file content, stripping trailing whitespace."""
    return Path(path).read_text().strip()


def embed(html: str, const_name: str, csv_content: str) -> str:
    """Replace or insert a JS string constant with CSV content."""
    # Pattern: const CONST_NAME = `...`;
    pattern = rf"(const {const_name} = `)\n.*?(`;\s*)"
    replacement = f"const {const_name} = `\n{csv_content}\n`;\n"

    if re.search(pattern, html, re.DOTALL):
        return re.sub(pattern, replacement, html, flags=re.DOTALL)
    else:
        # Insert before DataStore module
        marker = "// DATASTORE MODULE"
        return html.replace(marker, f"{replacement}\n{marker}")


def embed_backtest(html: str, fragment_path: str) -> str:
    """Replace content between BACKTEST_START/END markers with fragment HTML."""
    fragment = Path(fragment_path).read_text(encoding="utf-8").strip()
    start_marker = "<!-- BACKTEST_START -->"
    end_marker = "<!-- BACKTEST_END -->"
    start_idx = html.index(start_marker)
    end_idx = html.index(end_marker) + len(end_marker)
    return html[:start_idx] + start_marker + "\n" + fragment + "\n" + end_marker + html[end_idx:]


def main():
    import argparse
    p = argparse.ArgumentParser(description="Embed CSV data into dashboard HTML")
    p.add_argument("--date", default=None, help="Date suffix for CSV files (YYYYMMDD)")
    p.add_argument("--backtest", default=None, help="Path to backtest_tab_fragment.html")
    p.add_argument("--dashboard", default="dashboard/bitmor-dashboard.html")
    args = p.parse_args()

    html = Path(args.dashboard).read_text()

    # Embed tier CSVs (if --date provided)
    if args.date:
        d = args.date
        result_dir = Path("results")

        for tier in [1, 2, 3]:
            csv_path = result_dir / f"rolldown_tier{tier}_{d}.csv"
            if csv_path.exists():
                html = embed(html, f"TIER{tier}_CSV", read_csv(csv_path))
                print(f"Embedded {csv_path}")

        for tier in [1, 2, 3]:
            csv_path = result_dir / f"rolldown_tier{tier}_detail_{d}.csv"
            if csv_path.exists():
                html = embed(html, f"TIER{tier}_DETAIL_CSV", read_csv(csv_path))
                print(f"Embedded {csv_path}")

    # Embed backtest fragment (if --backtest provided)
    if args.backtest:
        html = embed_backtest(html, args.backtest)
        print(f"Embedded backtest from {args.backtest}")

    Path(args.dashboard).write_text(html)
    print(f"Updated {args.dashboard}")


if __name__ == "__main__":
    main()
