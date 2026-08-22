"""Tests for punt_lux._binary_sweep_disk -- disk binary shim cleanup."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux._binary_sweep_disk import DiskBinaryLegacySweep
from punt_lux._service_errors import ServiceMigrationError
from punt_lux.service import HUB_SPEC

_SPEC = replace(HUB_SPEC, legacy_binary_names=("luxd",))


def _plant_owned_shim(tmp_path: Path, bin_dir: Path, name: str) -> Path:
    """Reproduce the exact two-hop shape observed on the real machine."""
    tool_root = tmp_path / "uv-tools" / "punt-lux" / "bin"
    tool_root.mkdir(parents=True)
    shim = tool_root / name
    shim.write_text("#!/fake/venv/bin/python3\nfrom punt_lux.luxd import main\n")
    shim.chmod(0o755)
    link = bin_dir / name
    link.symlink_to(shim)
    return link


def _plant_sibling_package_shim(tmp_path: Path, bin_dir: Path, name: str) -> Path:
    """Reproduce the exact false positive ``str.startswith()`` would accept:
    a sibling uv tool whose directory name merely starts with ours."""
    sibling_root = tmp_path / "uv-tools" / "punt-lux-devtools" / "bin"
    sibling_root.mkdir(parents=True)
    shim = sibling_root / name
    shim.write_text("#!/fake/venv/bin/python3\nfrom other_pkg import main\n")
    shim.chmod(0o755)
    link = bin_dir / name
    link.symlink_to(shim)
    return link


def _tool_dir_result(tool_dir: Path) -> object:
    class _Result:
        returncode = 0
        stdout = f"{tool_dir}\n"
        stderr = ""

    return _Result()


class TestDiskBinarySweepPositive:
    def test_sweep_removes_an_owned_shim(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "home" / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        link = _plant_owned_shim(tmp_path, bin_dir, "luxd")

        with (
            patch(
                "punt_lux._binary_sweep_disk.Path.home", return_value=tmp_path / "home"
            ),
            patch(
                "punt_lux._binary_sweep_disk.subprocess.run",
                return_value=_tool_dir_result(tmp_path / "uv-tools"),
            ),
        ):
            sweep = DiskBinaryLegacySweep(_SPEC)
            report = sweep.sweep()

        assert report.all_clean
        assert not link.exists()
        assert not link.is_symlink()
        assert report.outcomes[0].ownership_verified is True


class TestDiskBinarySweepRefusesUnverifiedTarget:
    def test_sweep_refuses_a_foreign_script_and_leaves_it_in_place(
        self, tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "home" / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        foreign = bin_dir / "luxd"
        foreign.write_text('#!/bin/sh\necho "my own script"\n')
        foreign.chmod(0o755)

        with (
            patch(
                "punt_lux._binary_sweep_disk.Path.home", return_value=tmp_path / "home"
            ),
            patch(
                "punt_lux._binary_sweep_disk.subprocess.run",
                return_value=_tool_dir_result(tmp_path / "uv-tools"),
            ),
        ):
            sweep = DiskBinaryLegacySweep(_SPEC)
            with pytest.raises(ServiceMigrationError):
                sweep.sweep()

        assert foreign.exists()
        with (
            patch(
                "punt_lux._binary_sweep_disk.Path.home", return_value=tmp_path / "home"
            ),
            patch(
                "punt_lux._binary_sweep_disk.subprocess.run",
                return_value=_tool_dir_result(tmp_path / "uv-tools"),
            ),
        ):
            report = DiskBinaryLegacySweep(_SPEC).diagnose()
        assert report.outcomes[0].ownership_verified is False


class TestDiskBinarySweepSiblingPackageRegression:
    """Regression test for the exact startswith() bug: a sibling tool
    directory (``punt-lux-devtools``) must never be treated as ours."""

    def test_sweep_refuses_a_sibling_package_shim(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "home" / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        link = _plant_sibling_package_shim(tmp_path, bin_dir, "luxd")

        with (
            patch(
                "punt_lux._binary_sweep_disk.Path.home", return_value=tmp_path / "home"
            ),
            patch(
                "punt_lux._binary_sweep_disk.subprocess.run",
                return_value=_tool_dir_result(tmp_path / "uv-tools"),
            ),
        ):
            sweep = DiskBinaryLegacySweep(_SPEC)
            with pytest.raises(ServiceMigrationError):
                sweep.sweep()

        assert link.exists()
        assert link.is_symlink()
        with (
            patch(
                "punt_lux._binary_sweep_disk.Path.home", return_value=tmp_path / "home"
            ),
            patch(
                "punt_lux._binary_sweep_disk.subprocess.run",
                return_value=_tool_dir_result(tmp_path / "uv-tools"),
            ),
        ):
            report = DiskBinaryLegacySweep(_SPEC).diagnose()
        assert report.outcomes[0].ownership_verified is False


class TestDiskBinarySweepIdempotency:
    def test_sweep_on_a_clean_bin_dir_touches_nothing(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "home" / ".local" / "bin"
        bin_dir.mkdir(parents=True)

        with (
            patch(
                "punt_lux._binary_sweep_disk.Path.home", return_value=tmp_path / "home"
            ),
            patch("punt_lux._binary_sweep_disk.subprocess.run") as run,
        ):
            sweep = DiskBinaryLegacySweep(_SPEC)
            report = sweep.sweep()

        assert report.all_clean
        assert report.outcomes[0].was_present is False
        # No luxd file exists, so the ownership check -- and the uv subprocess
        # call it would trigger -- never runs at all.
        run.assert_not_called()


class TestDiskBinarySweepUvAbsent:
    def test_sweep_refuses_when_uv_is_not_on_path(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "home" / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        link = _plant_owned_shim(tmp_path, bin_dir, "luxd")

        with (
            patch(
                "punt_lux._binary_sweep_disk.Path.home", return_value=tmp_path / "home"
            ),
            patch(
                "punt_lux._binary_sweep_disk.subprocess.run",
                side_effect=FileNotFoundError,
            ),
        ):
            sweep = DiskBinaryLegacySweep(_SPEC)
            with pytest.raises(ServiceMigrationError):
                sweep.sweep()

        assert link.exists()
        assert link.is_symlink()
