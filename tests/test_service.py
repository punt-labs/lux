"""Tests for punt_lux.service -- daemon lifecycle management."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux._backends import LaunchdBackend, SystemdBackend
from punt_lux.service import ServiceManager, detect_platform


class TestDetectPlatform:
    def test_darwin(self):
        with patch.object(platform, "system", return_value="Darwin"):
            assert detect_platform() == "macos"

    def test_linux(self):
        with patch.object(platform, "system", return_value="Linux"):
            assert detect_platform() == "linux"

    def test_unsupported(self):
        with (
            patch.object(platform, "system", return_value="Windows"),
            pytest.raises(SystemExit, match="Unsupported platform"),
        ):
            detect_platform()


class TestLuxdExecArgs:
    def test_raises_when_binary_missing(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with (
            patch("punt_lux.service.Path.home", return_value=fake_home),
            pytest.raises(RuntimeError, match="Cannot find luxd binary"),
        ):
            ServiceManager._luxd_exec_args()

    def test_resolves_binary(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        luxd = local_bin / "luxd"
        luxd.touch()
        luxd.chmod(0o755)

        with patch("punt_lux.service.Path.home", return_value=fake_home):
            args = ServiceManager._luxd_exec_args()

        assert args[0].endswith("luxd")
        assert "--port" in args
        assert "8430" in args


class TestLaunchdPlistContent:
    def test_generates_valid_xml(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        luxd = local_bin / "luxd"
        luxd.touch()
        luxd.chmod(0o755)

        with patch("punt_lux._backends.Path.home", return_value=fake_home):
            backend = LaunchdBackend()
            exec_args = [str(luxd), "--port", "8430"]
            content = backend._plist_content(exec_args)

        assert '<?xml version="1.0"' in content
        assert "<plist" in content
        assert "com.punt-labs.lux" in content
        assert "KeepAlive" in content
        assert "RunAtLoad" in content
        assert "luxd-stdout.log" in content
        assert "luxd-stderr.log" in content

    def test_contains_program_arguments(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        luxd = local_bin / "luxd"
        luxd.touch()
        luxd.chmod(0o755)

        with patch("punt_lux._backends.Path.home", return_value=fake_home):
            backend = LaunchdBackend()
            exec_args = [str(luxd), "--port", "8430"]
            content = backend._plist_content(exec_args)

        assert "ProgramArguments" in content
        assert "--port" in content
        assert "8430" in content


class TestSystemdUnitContent:
    def test_generates_valid_unit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        luxd = local_bin / "luxd"
        luxd.touch()
        luxd.chmod(0o755)

        with patch("punt_lux._backends.Path.home", return_value=fake_home):
            backend = SystemdBackend()
            exec_args = [str(luxd), "--port", "8430"]
            content = backend._unit_content(exec_args)

        assert "[Unit]" in content
        assert "[Service]" in content
        assert "[Install]" in content
        assert "Lux session hub daemon" in content
        assert "Restart=on-failure" in content
        assert "RestartSec=5" in content
        assert "WantedBy=default.target" in content

    def test_contains_exec_start(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        luxd = local_bin / "luxd"
        luxd.touch()
        luxd.chmod(0o755)

        with patch("punt_lux._backends.Path.home", return_value=fake_home):
            backend = SystemdBackend()
            exec_args = [str(luxd), "--port", "8430"]
            content = backend._unit_content(exec_args)

        assert "ExecStart=" in content
        assert "luxd" in content
        assert "--port" in content


class TestServiceManager:
    def test_resolves_macos_backend(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager()
        assert isinstance(mgr._backend, LaunchdBackend)

    def test_resolves_linux_backend(self):
        with patch("punt_lux.service.detect_platform", return_value="linux"):
            mgr = ServiceManager()
        assert isinstance(mgr._backend, SystemdBackend)
