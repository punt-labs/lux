"""The Beads applet package imports cleanly and the old ``apps`` paths are gone."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src"
_BEADS = _SRC / "punt_lux" / "applets" / "beads"
_MODULES = sorted(
    ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
    for path in _BEADS.rglob("*.py")
)
_OLD_MODULES = [
    "punt_lux.apps",
    "punt_lux.apps.beads",
    "punt_lux.apps.beads_board",
    "punt_lux.apps.bd_child",
    "punt_lux.applets.beads_service",
    "punt_lux.applets.beads_source",
]


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("module", _MODULES)
def test_beads_module_imports_in_fresh_process(module: str) -> None:
    result = _run(f"import {module}")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", _OLD_MODULES)
def test_old_module_path_has_no_alias(module: str) -> None:
    result = _run(
        "import importlib, sys\n"
        "try:\n"
        f"    importlib.import_module({module!r})\n"
        "except ModuleNotFoundError:\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    assert result.returncode == 0, f"{module} still resolves"
