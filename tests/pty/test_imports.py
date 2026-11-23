"""The PTY owner imports in fresh interpreters without its old package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_MODULES = sorted(
    ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
    for path in (_SRC / "punt_lux" / "pty").rglob("*.py")
)


@pytest.mark.parametrize("module", _MODULES)
def test_pty_module_imports_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_old_pty_package_has_no_alias() -> None:
    code = (
        "import importlib\n"
        "try:\n"
        "    importlib.import_module('punt_lux.ptyd')\n"
        "except ModuleNotFoundError as exc:\n"
        "    if exc.name != 'punt_lux.ptyd':\n"
        "        raise\n"
        "else:\n"
        "    raise AssertionError('old PTY package still imports')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
