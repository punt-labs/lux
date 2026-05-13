#!/usr/bin/env python3
"""Test coverage runner for punt-lux.

Runs pytest with coverage measurement and generates terminal + HTML reports.
"""

from __future__ import annotations

import subprocess
import sys


def run_coverage() -> None:
    """Run tests with coverage and generate reports."""
    subprocess.run(["coverage", "erase"], check=True)

    result = subprocess.run(
        [
            "coverage",
            "run",
            "--source=src/punt_lux",
            "-m",
            "pytest",
            "--ignore=tests/test_display_partition.py",
            "--ignore=tests/test_display_refinement.py",
            "--ignore=tests/test_display_state.py",
            "-q",
        ],
        check=False,
    )

    if result.returncode not in (0, 5):
        print(f"Tests exited with code {result.returncode}", file=sys.stderr)

    subprocess.run(["coverage", "report", "-m"], check=True)
    subprocess.run(["coverage", "html"], check=True)

    print("\nHTML coverage report: htmlcov/index.html")


if __name__ == "__main__":
    run_coverage()
