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


def main():
    import argparse
    p = argparse.ArgumentParser(description="Embed CSV data into dashboard HTML")
    p.add_argument("--date", required=True, help="Date suffix for CSV files (YYYYMMDD)")
    p.add_argument("--dashboard", default="bitmor-dashboard.html")
    args = p.parse_args()

    d = args.date
    result_dir = Path("result")

    html = Path(args.dashboard).read_text()

    # Embed summary CSVs
    for tier in [1, 2, 3]:
        csv_path = result_dir / f"rolldown_tier{tier}_{d}.csv"
        if csv_path.exists():
            html = embed(html, f"TIER{tier}_CSV", read_csv(csv_path))
            print(f"Embedded {csv_path}")

    # Embed detail CSVs (Tier 1 and 3 only)
    for tier in [1, 3]:
        csv_path = result_dir / f"rolldown_tier{tier}_detail_{d}.csv"
        if csv_path.exists():
            html = embed(html, f"TIER{tier}_DETAIL_CSV", read_csv(csv_path))
            print(f"Embedded {csv_path}")

    Path(args.dashboard).write_text(html)
    print(f"Updated {args.dashboard}")


if __name__ == "__main__":
    main()
