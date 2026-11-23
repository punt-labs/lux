"""The promoted Hub modules initialize independently without DNS I/O."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_HUB = _SRC / "punt_lux" / "hub"
_MODULES = sorted(
    ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
    for path in _HUB.rglob("*.py")
)


@pytest.mark.parametrize("module", _MODULES)
def test_hub_module_imports_in_fresh_process(module: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from unittest.mock import patch; "
                "guard = patch('socket.getfqdn', side_effect=AssertionError('DNS')); "
                "guard.start(); "
                f"import {module}"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
