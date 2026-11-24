"""Workspace preparation physically removes single-file root modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fresh_imports import (
    assert_importable,
    assert_isolated,
    assert_not_importable,
)
from tests.root_module_moves import MOVED_MODULES


@pytest.mark.parametrize("module", sorted(MOVED_MODULES))
def test_old_module_is_not_importable(module: str) -> None:
    assert_not_importable(module)


@pytest.mark.parametrize("module", sorted(MOVED_MODULES.values()))
def test_package_owned_module_imports(module: str) -> None:
    assert_importable(module)


def test_namespace_root_has_no_python_modules() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "punt_lux"
    assert not list(source.glob("*.py"))


@pytest.mark.parametrize(
    "module",
    [
        "punt_lux.service.terminal_service",
        "punt_lux.service.display_foreground",
        "punt_lux.commands",
    ],
)
def test_lifecycle_and_commands_do_not_load_daemons(module: str) -> None:
    assert_isolated(
        module,
        ("punt_lux.hub", "punt_lux.display", "punt_lux.pty", "punt_lux.operations"),
    )
