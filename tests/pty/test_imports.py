"""The PTY owner imports in fresh interpreters without its old package."""

from __future__ import annotations

import pytest

from tests.fresh_imports import (
    assert_importable,
    assert_not_importable,
    package_modules,
)


@pytest.mark.parametrize("module", package_modules("punt_lux.pty"))
def test_pty_module_imports_in_a_fresh_interpreter(module: str) -> None:
    assert_importable(module)


def test_old_pty_package_has_no_alias() -> None:
    assert_not_importable("punt_lux.ptyd")
