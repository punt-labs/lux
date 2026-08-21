"""Tests for punt_lux.service -- daemon lifecycle management."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux._backend_launchd import LaunchdBackend
from punt_lux._backend_systemd import SystemdBackend
from punt_lux.service import (
    ServiceActionFailedError,
    ServiceManager,
    ServiceNotInstalledError,
    detect_platform,
)


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

        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend()
            exec_args = [str(luxd), "--port", "8430"]
            content = backend._plist_content(exec_args)

        assert '<?xml version="1.0"' in content
        assert "<plist" in content
        assert "com.punt-labs.luxd-hub" in content
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

        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
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

        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
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

        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
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


class TestServiceManagerStart:
    def test_raises_when_not_installed(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager()
        with (
            patch.object(
                mgr._backend, "config_path", return_value=Path("/nonexistent")
            ),
            pytest.raises(ServiceNotInstalledError, match="lux hub install"),
        ):
            mgr.start()

    def test_starts_the_backend_when_installed(self, tmp_path: Path):
        config = tmp_path / "com.punt-labs.lux.plist"
        config.touch()
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager()
        with (
            patch.object(mgr._backend, "config_path", return_value=config),
            patch.object(mgr._backend, "start", return_value=True) as backend_start,
        ):
            result = mgr.start()
        backend_start.assert_called_once()
        assert result == "luxd started."

    def test_raises_when_the_backend_call_fails(self, tmp_path: Path):
        config = tmp_path / "com.punt-labs.lux.plist"
        config.touch()
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager()
        with (
            patch.object(mgr._backend, "config_path", return_value=config),
            patch.object(mgr._backend, "start", return_value=False),
            pytest.raises(ServiceActionFailedError, match="luxd start failed"),
        ):
            mgr.start()


class TestServiceManagerStop:
    def test_reports_stopped_when_the_backend_call_succeeds(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager()
        with patch.object(mgr._backend, "stop", return_value=True):
            result = mgr.stop()
        assert result == "luxd stopped."

    def test_raises_when_the_backend_call_fails(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager()
        with (
            patch.object(mgr._backend, "stop", return_value=False),
            pytest.raises(ServiceActionFailedError, match="luxd stop failed"),
        ):
            mgr.stop()


class TestBackendStartStopSymmetry:
    def test_launchd_start_calls_launchctl_load(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend()
        with patch("punt_lux._backend_launchd.subprocess.run") as run:
            run.return_value.returncode = 0
            ok = backend.start()
        assert run.call_args[0][0][:2] == ["launchctl", "load"]
        assert ok is True

    def test_launchd_start_reports_failure_on_nonzero_exit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend()
        with patch("punt_lux._backend_launchd.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            ok = backend.start()
        assert ok is False

    def test_systemd_start_calls_systemctl_start(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
            backend = SystemdBackend()
        with patch("punt_lux._backend_systemd.subprocess.run") as run:
            run.return_value.returncode = 0
            ok = backend.start()
        assert run.call_args[0][0] == ["systemctl", "--user", "start", "luxd-hub"]
        assert ok is True

    def test_systemd_start_reports_failure_on_nonzero_exit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
            backend = SystemdBackend()
        with patch("punt_lux._backend_systemd.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            ok = backend.start()
        assert ok is False
