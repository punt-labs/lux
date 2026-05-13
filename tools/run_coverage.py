#!/usr/bin/env python3
"""Test coverage runner for punt-lux.

Runs pytest with coverage measurement and generates terminal + HTML reports.
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def _resolve_coverage() -> str:
    """Return the full path to the coverage executable."""
    path = shutil.which("coverage")
    if path is None:
        print("coverage not found", file=sys.stderr)
        sys.exit(1)
    return path


def run_coverage() -> None:
    """Run tests with coverage and generate reports."""
    cov = _resolve_coverage()

    subprocess.run([cov, "erase"], check=True)  # noqa: S603

    result = subprocess.run(  # noqa: S603
        [
            cov,
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
        sys.exit(result.returncode)

    subprocess.run([cov, "report", "-m"], check=True)  # noqa: S603
    subprocess.run([cov, "html"], check=True)  # noqa: S603

    print("\nHTML coverage report: htmlcov/index.html")


if __name__ == "__main__":
    run_coverage()
