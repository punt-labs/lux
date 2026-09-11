"""Tests for CaPaths: path derivation, existence, directory creation."""

from __future__ import annotations

import stat
from pathlib import Path

from punt_lux.trust.ca_paths import CaPaths


def test_paths_derive_from_the_root(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path)
    assert paths.dir == tmp_path
    assert paths.root_key_path == tmp_path / "root.key"
    assert paths.root_cert_path == tmp_path / "root.crt"


def test_default_root_is_under_punt_labs_lux_ca() -> None:
    paths = CaPaths.default()
    assert paths.dir == Path.home() / ".punt-labs" / "lux" / "ca"


def test_exists_is_false_before_any_material_is_written(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path)
    assert paths.exists() is False


def test_exists_is_false_when_only_the_key_is_present(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path)
    paths.ensure_dir()
    paths.root_key_path.write_bytes(b"key")
    assert paths.exists() is False


def test_exists_is_true_once_both_key_and_cert_are_present(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path)
    paths.ensure_dir()
    paths.root_key_path.write_bytes(b"key")
    paths.root_cert_path.write_bytes(b"cert")
    assert paths.exists() is True


def test_ensure_dir_creates_the_directory_as_0700(tmp_path: Path) -> None:
    root = tmp_path / "ca"
    paths = CaPaths(root)
    paths.ensure_dir()
    assert root.is_dir()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_ensure_dir_is_idempotent(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path / "ca")
    paths.ensure_dir()
    paths.ensure_dir()  # must not raise on an already-existing directory
    assert paths.dir.is_dir()


def test_ensure_dir_normalizes_a_preexisting_insecure_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ca"
    root.mkdir(mode=0o755)
    paths = CaPaths(root)
    paths.ensure_dir()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
