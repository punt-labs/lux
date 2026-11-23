"""The model gate rejects absent tools and incomplete or defective reports."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "verify_readiness_model.sh"


def _run(
    tmp_path: Path, report: str, *, fuzz_exists: bool = True
) -> subprocess.CompletedProcess[str]:
    fuzz = tmp_path / "fuzz"
    prob = tmp_path / "probcli"
    if fuzz_exists:
        fuzz.write_text("#!/bin/sh\nexit 0\n")
        fuzz.chmod(0o755)
    prob.write_text("#!/bin/sh\n" + report)
    prob.chmod(0o755)
    return subprocess.run(
        [shutil.which("bash") or "/bin/bash", str(_SCRIPT)],
        cwd=_ROOT,
        env={**os.environ, "FUZZ": str(fuzz), "PROBCLI": str(prob)},
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_report_parser_tolerates_spacing_and_counterexample_spelling(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        """
printf 'States analysed: 3\\n'
case "$1" in
  */display_restart_readiness.tex)
    printf 'No counter-example found. ALL states visited.\\n'
    ;;
  *)
    printf 'Found   GOAL in state id 3\\n'
    printf '! Total   Errors:   1, Warnings: 0\\n!   goal_found\\n'
    ;;
esac
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: all readiness model checks" in result.stdout
    assert "stale-pid-fidelity found" in result.stdout
    assert "second-pid-fidelity found" in result.stdout


@pytest.mark.parametrize(
    "report",
    [
        "exit 0\n",
        (
            "printf 'No counter example found. ALL states visited.\\n'\n"
            "printf '! Total Errors: 2, Warnings: 0\\n'\n"
        ),
    ],
)
def test_empty_or_error_reports_do_not_pass(tmp_path: Path, report: str) -> None:
    result = _run(tmp_path, report)
    assert result.returncode != 0
    assert "incomplete or unsafe" in result.stderr


def test_missing_tool_has_an_actionable_error(tmp_path: Path) -> None:
    result = _run(tmp_path, "exit 0\n", fuzz_exists=False)
    assert result.returncode != 0
    assert "required verification binary not found" in result.stderr
    assert str(tmp_path / "fuzz") in result.stderr
