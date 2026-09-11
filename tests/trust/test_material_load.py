"""Tests for MaterialLoad: wrapping a load failure with directory context."""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.trust.material_load import MaterialLoad


def test_or_raise_clearly_returns_the_loaded_value(tmp_path: Path) -> None:
    result = MaterialLoad.or_raise_clearly(tmp_path, lambda: "loaded")
    assert result == "loaded"


def test_or_raise_clearly_wraps_a_value_error(tmp_path: Path) -> None:
    def _boom() -> None:
        msg = "underlying failure"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="damaged or incomplete") as exc_info:
        MaterialLoad.or_raise_clearly(tmp_path, _boom)
    assert str(tmp_path) in str(exc_info.value)


def test_or_raise_clearly_wraps_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "root.crt"

    with pytest.raises(ValueError, match="damaged or incomplete") as exc_info:
        MaterialLoad.or_raise_clearly(tmp_path, missing.read_bytes)
    assert str(tmp_path) in str(exc_info.value)
    # The bare FileNotFoundError never escapes — it's the wrapped cause.
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_or_raise_clearly_propagates_unrelated_errors(tmp_path: Path) -> None:
    def _boom() -> None:
        raise TypeError

    with pytest.raises(TypeError):
        MaterialLoad.or_raise_clearly(tmp_path, _boom)
