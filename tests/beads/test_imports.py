"""The Beads applet package imports cleanly and the old ``apps`` paths are gone."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_BEADS = _SRC / "punt_lux" / "beads"
_MODULES = sorted(
    ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
    for path in _BEADS.rglob("*.py")
)
_OLD_MODULES = [
    "punt_lux.applets.beads",
    "punt_lux.applets.beads.bd_child",
    "punt_lux.applets.beads.bd_exit",
    "punt_lux.apps",
    "punt_lux.apps.beads",
    "punt_lux.apps.beads_board",
    "punt_lux.apps.bd_child",
    "punt_lux.applets.beads_service",
    "punt_lux.applets.beads_source",
    "punt_lux.applets.applet_board",
    "punt_lux.applets.board_load",
    "punt_lux.applets.board_read",
    "punt_lux.applets.held_board",
    "punt_lux.applets.no_board",
]


def test_beads_import_inventory_is_nonempty() -> None:
    assert "punt_lux.beads.applet" in _MODULES


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


def _old_module_probe(module: str) -> str:
    return (
        "import importlib, sys\n"
        f"name = {module!r}\n"
        "try:\n"
        "    importlib.import_module(name)\n"
        "except ModuleNotFoundError as exc:\n"
        "    if exc.name and (name == exc.name or name.startswith(exc.name + '.')):\n"
        "        sys.exit(0)\n"
        "    raise\n"
        "sys.exit(1)\n"
    )


@pytest.mark.parametrize("module", _OLD_MODULES)
def test_old_module_path_has_no_alias(module: str) -> None:
    result = _run(_old_module_probe(module))
    assert result.returncode == 0, (
        f"{module} resolved or failed unexpectedly:\n{result.stderr}"
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "import missing_dependency_for_old_module_test\n",
        "raise ModuleNotFoundError\n",
    ],
)
def test_old_module_probe_rejects_an_existing_module(
    tmp_path: Path, content: str
) -> None:
    (tmp_path / "legacy_old_app.py").write_text(content)
    result = _run(
        f"import sys; sys.path.insert(0, {str(tmp_path)!r})\n"
        + _old_module_probe("legacy_old_app")
    )
    assert result.returncode != 0
