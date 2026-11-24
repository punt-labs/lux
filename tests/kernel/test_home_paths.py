"""Verify the product home path does not depend on the checkout."""

from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.kernel.home_paths import LuxHome


def test_product_home_is_independent_of_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(checkout)

    assert LuxHome.resolve().root == home / ".punt-labs" / "lux"


def test_unavailable_home_does_not_fall_back_to_checkout() -> None:
    with (
        patch.object(
            Path, "home", side_effect=RuntimeError("Could not determine home")
        ),
        pytest.raises(RuntimeError, match="Could not determine home"),
    ):
        LuxHome.resolve()


def test_relative_home_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "relative-home")

    with pytest.raises(RuntimeError, match="absolute home directory"):
        LuxHome.resolve()
