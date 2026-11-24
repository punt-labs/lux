"""The registry model gate requires exhaustive safety and real defect witnesses."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "verify_peripheral_registry_model.sh"
_SAFE = (
    "printf 'No counter-example found. ALL states visited.\\n'\n"
    "printf '! Total Errors: 0, Warnings: 0\\n'\n"
)
_WITNESS = (
    "printf 'Found GOAL in state id 3\\n'\n"
    "printf '! Total Errors: 1, Warnings: 0\\n! goal_found\\n'\n"
)


def _run(
    tmp_path: Path,
    safe: str = _SAFE,
    witness: str = _WITNESS,
    *,
    fuzz_exists: bool = True,
    fuzz_report: str = "exit 0\n",
) -> subprocess.CompletedProcess[str]:
    fuzz = tmp_path / "fuzz"
    prob = tmp_path / "probcli"
    if fuzz_exists:
        fuzz.write_text("#!/bin/sh\n" + fuzz_report)
        fuzz.chmod(0o755)
    prob.write_text(
        "#!/bin/sh\n"
        "printf 'States analysed: 3\\n'\n"
        'case "$1" in\n'
        "*/peripheral_registry_lifecycle.tex)\n"
        f"{safe};;\n*)\n{witness};;\nesac\n"
    )
    prob.chmod(0o755)
    return subprocess.run(
        [shutil.which("bash") or "/bin/bash", str(_SCRIPT)],
        cwd=_ROOT,
        env={**os.environ, "FUZZ": str(fuzz), "PROBCLI": str(prob)},
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_exhaustive_safety_and_all_fidelity_witnesses_pass(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "registry-safety not found" in result.stdout
    assert "registry-deadlock not found" in result.stdout
    assert result.stdout.count("-fidelity found") == 7
    assert "PASS: all peripheral registry model checks" in result.stdout


def test_verbose_summary_supplies_explicit_zero(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "printf 'No counter example found. ALL states visited.\\n'\n"
        "printf '%% Finished model_check (errors=0, warnings=0, expected_errors=0)\\n'\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "safe",
    [
        "exit 0\n",
        "printf '! Total Errors: 0, Warnings: 0\\n'\n",
        "printf 'No counter example found. ALL states visited.\\n'\n",
        _SAFE.replace("Errors: 0", "Errors: 0oops"),
        _SAFE.replace("Errors: 0", "Errors: 2"),
    ],
)
def test_incomplete_or_unsafe_reports_fail(tmp_path: Path, safe: str) -> None:
    result = _run(tmp_path, safe)
    assert result.returncode != 0
    assert "registry-safety incomplete or unsafe" in result.stderr


@pytest.mark.parametrize(
    "witness",
    [
        _SAFE,
        _WITNESS.replace("! goal_found", ""),
        _WITNESS.replace("Errors: 1", "Errors: 2"),
        _WITNESS.replace("Found GOAL in state id 3", ""),
    ],
)
def test_missing_or_ambiguous_defect_witness_fails(
    tmp_path: Path, witness: str
) -> None:
    result = _run(tmp_path, witness=witness)
    assert result.returncode != 0
    assert "duplicate-kind-fidelity expected defect witness" in result.stderr


def test_missing_tool_is_an_error(tmp_path: Path) -> None:
    result = _run(tmp_path, fuzz_exists=False)
    assert result.returncode != 0
    assert "required verification binary not found" in result.stderr


def test_fuzz_failure_is_an_error(tmp_path: Path) -> None:
    result = _run(tmp_path, fuzz_report="exit 1\n")
    assert result.returncode != 0
    assert "peripheral_registry_lifecycle fuzz" in result.stderr
