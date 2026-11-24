"""Verify the product home path does not depend on the checkout."""

import os
import stat
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


def test_prepare_root_rejects_symlink_to_foreign_owned_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    home = LuxHome.resolve()
    home.root.parent.mkdir(mode=0o700)
    target = tmp_path / "foreign"
    target.mkdir(mode=0o700)
    home.root.symlink_to(target, target_is_directory=True)
    lstat = Path.lstat

    def foreign_owner(path: Path) -> os.stat_result:
        info = lstat(path)
        if path == target:
            return os.stat_result((*info[:4], os.getuid() + 1, *info[5:]))
        return info

    monkeypatch.setattr(Path, "lstat", foreign_owner)
    with pytest.raises(PermissionError, match="not an owned directory"):
        home.prepare_root()


def test_prepare_root_rejects_a_link_inserted_during_namespace_repair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    home = LuxHome.resolve()
    namespace = home.root.parent
    namespace.mkdir()
    namespace.chmod(0o775)
    target = tmp_path / "unrelated"
    target.mkdir()
    target.chmod(0o755)
    chmod = Path.chmod

    def insert_link(path: Path, mode: int) -> None:
        if path == namespace and mode == 0o700:
            home.root.symlink_to(target, target_is_directory=True)
        chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", insert_link)
    with pytest.raises(PermissionError, match="symlink in a writable directory"):
        home.prepare_root()
    assert stat.S_IMODE(namespace.stat().st_mode) == 0o775
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
