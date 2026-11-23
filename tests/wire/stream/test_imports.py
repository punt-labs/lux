"""Stream contracts import under wire, never through the old protocol package."""

from __future__ import annotations

import pytest

from tests.fresh_imports import (
    assert_importable,
    assert_not_importable,
    package_modules,
)


@pytest.mark.parametrize("module", package_modules("punt_lux.wire.stream"))
def test_stream_module_imports_in_a_fresh_interpreter(module: str) -> None:
    assert_importable(module)


def test_old_stream_package_has_no_alias() -> None:
    assert_not_importable("punt_lux.protocol.pty")
