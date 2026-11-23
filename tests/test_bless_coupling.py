"""Bounded bless dispatch matches the two coupling gate scopes."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make") or "/usr/bin/make"


@pytest.fixture
def recorder(tmp_path: Path) -> tuple[dict[str, str], Path]:
    executable = tmp_path / "uv"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['CALLS'], 'a') as output:\n"
        "    output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(7 if os.environ.get('FAIL') else 0)\n"
    )
    executable.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    return {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "CALLS": str(calls),
    }, calls


def test_bless_dispatches_each_file_to_its_gate_scope(
    recorder: tuple[dict[str, str], Path],
) -> None:
    env, log = recorder
    files = [
        "src/punt_lux/service/__init__.py",
        "packages/punt-lux-client/src/punt_lux/client/__init__.py",
        "packages/punt-service/src/punt_service/_backends.py",
        str(ROOT / "packages/punt-service/src/punt_service/_backends.py"),
    ]
    reason = "literal $(shell echo expanded) `echo expanded` $HOME"
    subprocess.run(
        [MAKE, "bless-coupling", f"FILES={','.join(files)}", f"REASON={reason}"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    gates = subprocess.run(
        [MAKE, "-n", "check-coupling"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert len(calls) == len(files)
    for call, file, scope in zip(calls, files, (0, 0, 1, 1), strict=True):
        assert call[:-4] == shlex.split(gates[scope])[1:-1]
        assert call[-4:] == ["--rebaseline-files", file, "--reason", reason]


@pytest.mark.parametrize("files", ["", "a.py,b.py"])
def test_empty_or_failed_bless_stops_without_further_writes(
    recorder: tuple[dict[str, str], Path], files: str
) -> None:
    env, log = recorder
    result = subprocess.run(
        [MAKE, "bless-coupling", f"FILES={files}", "REASON=test"],
        cwd=ROOT,
        env={**env, "FAIL": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    if files:
        assert len(log.read_text().splitlines()) == 1
    else:
        assert not log.exists()
