"""Tests for punt_lux.service -- daemon lifecycle management."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux._backend_launchd import LaunchdBackend
from punt_lux._backend_systemd import SystemdBackend
from punt_lux.service import (
    DISPLAY_SPEC,
    HUB_SPEC,
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


class TestHubSpecExecArgs:
    def test_raises_when_binary_missing(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with (
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
            pytest.raises(RuntimeError, match="Cannot find luxd binary"),
        ):
            HUB_SPEC.resolve_exec_args()

    def test_resolves_binary(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        luxd = local_bin / "luxd"
        luxd.touch()
        luxd.chmod(0o755)

        with patch("punt_lux._service_spec.Path.home", return_value=fake_home):
            args = HUB_SPEC.resolve_exec_args()

        assert args[0].endswith("luxd")
        assert "--port" in args
        assert "8430" in args


class TestDisplaySpecExecArgs:
    def test_resolves_lux_binary(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "lux").touch()
        (local_bin / "lux").chmod(0o755)

        with patch("punt_lux._service_spec.Path.home", return_value=fake_home):
            args = DISPLAY_SPEC.resolve_exec_args()

        assert args[0].endswith("lux")
        assert args[-2:] == ["display", "serve"]


class TestLaunchdPlistContent:
    def test_generates_valid_xml(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "luxd").touch()
        (local_bin / "luxd").chmod(0o755)

        with (
            patch("punt_lux._backend_launchd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
        ):
            backend = LaunchdBackend(HUB_SPEC)
            content = backend._plist_content()

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
        (local_bin / "luxd").touch()
        (local_bin / "luxd").chmod(0o755)

        with (
            patch("punt_lux._backend_launchd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
        ):
            backend = LaunchdBackend(HUB_SPEC)
            content = backend._plist_content()

        assert "ProgramArguments" in content
        assert "--port" in content
        assert "8430" in content

    def test_display_spec_carries_display_label(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "lux").touch()
        (local_bin / "lux").chmod(0o755)

        with (
            patch("punt_lux._backend_launchd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
        ):
            backend = LaunchdBackend(DISPLAY_SPEC)
            content = backend._plist_content()

        assert "com.punt-labs.luxd-display" in content
        assert "display" in content
        assert "serve" in content
        assert "luxd-display-stderr.log" in content


class TestSystemdUnitContent:
    def test_generates_valid_unit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "luxd").touch()
        (local_bin / "luxd").chmod(0o755)

        with (
            patch("punt_lux._backend_systemd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
        ):
            backend = SystemdBackend(HUB_SPEC)
            content = backend._unit_content()

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
        (local_bin / "luxd").touch()
        (local_bin / "luxd").chmod(0o755)

        with (
            patch("punt_lux._backend_systemd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
        ):
            backend = SystemdBackend(HUB_SPEC)
            content = backend._unit_content()

        assert "ExecStart=" in content
        assert "luxd" in content
        assert "--port" in content

    def test_display_spec_writes_display_unit_path(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
            backend = SystemdBackend(DISPLAY_SPEC)
        assert backend.config_path().name == "luxd-display.service"


class TestServiceManager:
    def test_for_hub_resolves_macos_backend(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        assert isinstance(mgr._backend, LaunchdBackend)
        assert mgr.spec is HUB_SPEC

    def test_for_hub_resolves_linux_backend(self):
        with patch("punt_lux.service.detect_platform", return_value="linux"):
            mgr = ServiceManager.for_hub()
        assert isinstance(mgr._backend, SystemdBackend)

    def test_for_display_resolves_macos_backend(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_display()
        assert isinstance(mgr._backend, LaunchdBackend)
        assert mgr.spec is DISPLAY_SPEC

    def test_bare_instantiation_raises_type_error(self):
        with pytest.raises(TypeError, match="abstract"):
            ServiceManager()

    def test_subclass_without_spec_raises_at_definition_time(self):
        with pytest.raises(TypeError, match="_SPEC"):
            type("Incomplete", (ServiceManager,), {"__slots__": ()})


class TestServiceManagerStart:
    def test_raises_when_not_installed(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with (
            patch.object(
                mgr._backend, "config_path", return_value=Path("/nonexistent")
            ),
            pytest.raises(ServiceNotInstalledError, match="lux hub install"),
        ):
            mgr.start()

    def test_display_raises_names_display_install_hint(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_display()
        with (
            patch.object(
                mgr._backend, "config_path", return_value=Path("/nonexistent")
            ),
            pytest.raises(ServiceNotInstalledError, match="lux display install"),
        ):
            mgr.start()

    def test_starts_the_backend_when_installed(self, tmp_path: Path):
        config = tmp_path / "com.punt-labs.luxd-hub.plist"
        config.touch()
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with (
            patch.object(mgr._backend, "config_path", return_value=config),
            patch.object(mgr._backend, "start", return_value=True) as backend_start,
        ):
            result = mgr.start()
        backend_start.assert_called_once()
        assert result == "luxd started."

    def test_raises_when_the_backend_call_fails(self, tmp_path: Path):
        config = tmp_path / "com.punt-labs.luxd-hub.plist"
        config.touch()
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with (
            patch.object(mgr._backend, "config_path", return_value=config),
            patch.object(mgr._backend, "start", return_value=False),
            pytest.raises(ServiceActionFailedError, match="luxd start failed"),
        ):
            mgr.start()


class TestServiceManagerStop:
    def test_reports_stopped_when_the_backend_call_succeeds(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with patch.object(mgr._backend, "stop", return_value=True):
            result = mgr.stop()
        assert result == "luxd stopped."

    def test_raises_when_the_backend_call_fails(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with (
            patch.object(mgr._backend, "stop", return_value=False),
            pytest.raises(ServiceActionFailedError, match="luxd stop failed"),
        ):
            mgr.stop()


class TestLegacyPlistCleanup:
    """ServiceManager.install() now owns the legacy sweep (service.py §2.1).

    The plist file itself is exercised via LaunchdLegacySweep's own tests
    (test_legacy_sweep.py); here the concern is that ServiceManager wires
    the sweep in for the hub and leaves DISPLAY_SPEC's empty
    legacy_launchd_labels tuple to no-op naturally, with zero string
    special-casing.
    """

    def test_hub_install_invokes_the_legacy_sweep(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "luxd").touch()

        with (
            patch("punt_lux.service.detect_platform", return_value="macos"),
            patch("punt_lux._backend_launchd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
            patch("punt_lux.hub_paths.Path.home", return_value=fake_home),
        ):
            mgr = ServiceManager.for_hub()
            with (
                patch.object(type(mgr._legacy_sweep), "sweep") as sweep,
                patch.object(mgr._backend, "install"),
                patch.object(mgr._backend, "is_active", return_value=True),
                patch.object(type(mgr._port_guard), "guard"),
            ):
                mgr.install()

        sweep.assert_called_once()

    def test_display_install_never_touches_the_legacy_sweep(self, tmp_path: Path):
        # DISPLAY_SPEC's legacy_launchd_labels is (); the sweep is still
        # invoked (uniform code path), but it has nothing to iterate --
        # exactly the "no if spec.launchd_label != ...: return" posture
        # the design replaces (§5.2).
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "lux").touch()

        with (
            patch("punt_lux.service.detect_platform", return_value="macos"),
            patch("punt_lux._backend_launchd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
            patch("punt_lux.hub_paths.Path.home", return_value=fake_home),
        ):
            mgr = ServiceManager.for_display()
            with (
                patch.object(mgr._backend, "install"),
                patch.object(mgr._backend, "is_active", return_value=True),
            ):
                report = mgr.install()

        assert mgr._legacy_sweep.is_clean()
        assert "displa" in report.lower() or report  # install() returned normally


class TestSystemdLegacyUnitCleanup:
    """Mirrors TestLegacyPlistCleanup for the systemd backend."""

    def test_hub_install_invokes_the_legacy_sweep(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "luxd").touch()

        with (
            patch("punt_lux.service.detect_platform", return_value="linux"),
            patch("punt_lux._backend_systemd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
        ):
            mgr = ServiceManager.for_hub()
            with (
                patch.object(type(mgr._legacy_sweep), "sweep") as sweep,
                patch.object(mgr._backend, "install"),
                patch.object(mgr._backend, "is_active", return_value=True),
                patch.object(type(mgr._port_guard), "guard"),
            ):
                mgr.install()

        sweep.assert_called_once()

    def test_display_install_has_nothing_to_sweep(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "lux").touch()

        with (
            patch("punt_lux.service.detect_platform", return_value="linux"),
            patch("punt_lux._backend_systemd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
        ):
            mgr = ServiceManager.for_display()
            with (
                patch.object(mgr._backend, "install"),
                patch.object(mgr._backend, "is_active", return_value=True),
            ):
                mgr.install()

        assert mgr._legacy_sweep.is_clean()


class TestServiceManagerRestart:
    def test_raises_when_not_installed(self):
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with (
            patch.object(
                mgr._backend, "config_path", return_value=Path("/nonexistent")
            ),
            pytest.raises(ServiceNotInstalledError, match="lux hub install"),
        ):
            mgr.restart()

    def test_restarts_the_backend_when_installed(self, tmp_path: Path):
        config = tmp_path / "com.punt-labs.luxd-hub.plist"
        config.touch()
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with (
            patch.object(mgr._backend, "config_path", return_value=config),
            patch.object(mgr._backend, "restart", return_value=True) as backend_restart,
        ):
            result = mgr.restart()
        backend_restart.assert_called_once()
        assert result == "luxd restarted."

    def test_raises_when_the_backend_call_fails(self, tmp_path: Path):
        config = tmp_path / "com.punt-labs.luxd-hub.plist"
        config.touch()
        with patch("punt_lux.service.detect_platform", return_value="macos"):
            mgr = ServiceManager.for_hub()
        with (
            patch.object(mgr._backend, "config_path", return_value=config),
            patch.object(mgr._backend, "restart", return_value=False),
            pytest.raises(ServiceActionFailedError, match="luxd restart failed"),
        ):
            mgr.restart()


class TestBackendStartStopSymmetry:
    def test_launchd_start_calls_launchctl_bootstrap(self, tmp_path: Path):
        # bootstrap, not load: the counterpart to stop's bootout, so a
        # service this backend stopped can be started again without
        # relying on the legacy load/unload shim (lux-5uc7 F5).
        #
        # start() calls launchctl.run(), not subprocess.run() directly —
        # patch the actual call site in _launchctl, not _backend_launchd's
        # module-level subprocess import (Copilot F1: the wrong-module patch
        # only works by accident, because subprocess is one shared module
        # object across every importer).
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend(HUB_SPEC)
        with patch("punt_lux._launchctl.subprocess.run") as run:
            run.return_value.returncode = 0
            ok = backend.start()
        assert run.call_args[0][0][:2] == ["launchctl", "bootstrap"]
        assert ok is True

    def test_launchd_stop_calls_launchctl_bootout(self, tmp_path: Path):
        # bootout, not unload/stop: under KeepAlive=true, launchctl stop
        # sends SIGTERM and launchd immediately respawns the job. bootout
        # deregisters it from the GUI domain so nothing respawns it
        # (lux-5uc7 F5 — the operator live-reproduced the respawn).
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend(HUB_SPEC)
        backend.config_path().parent.mkdir(parents=True, exist_ok=True)
        backend.config_path().write_text("<plist/>")
        with patch("punt_lux._launchctl.subprocess.run") as run:
            run.return_value.returncode = 0
            ok = backend.stop()
        args = run.call_args[0][0]
        assert args[:2] == ["launchctl", "bootout"]
        assert args[2].startswith("gui/")
        assert args[2].endswith(HUB_SPEC.launchd_label)
        assert ok is True

    def test_launchd_start_reports_failure_on_nonzero_exit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend(HUB_SPEC)
        with patch("punt_lux._launchctl.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            ok = backend.start()
        assert ok is False

    def test_systemd_start_calls_systemctl_start(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
            backend = SystemdBackend(HUB_SPEC)
        with patch("punt_lux._backend_systemd.subprocess.run") as run:
            run.return_value.returncode = 0
            ok = backend.start()
        assert run.call_args[0][0] == ["systemctl", "--user", "start", "luxd-hub"]
        assert ok is True

    def test_systemd_start_reports_failure_on_nonzero_exit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
            backend = SystemdBackend(HUB_SPEC)
        with patch("punt_lux._backend_systemd.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            ok = backend.start()
        assert ok is False

    def test_launchd_restart_calls_launchctl_kickstart(self, tmp_path: Path):
        # kickstart -k: one supervisor call that kills and respawns under the
        # same plist. No pid file consulted; the supervisor already knows the
        # pid the daemon does not itself keep current.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend(HUB_SPEC)
        with patch("punt_lux._launchctl.subprocess.run") as run:
            run.return_value.returncode = 0
            ok = backend.restart()
        args = run.call_args[0][0]
        assert args[:3] == ["launchctl", "kickstart", "-k"]
        assert args[3].startswith("gui/")
        assert args[3].endswith(HUB_SPEC.launchd_label)
        assert ok is True

    def test_launchd_restart_reports_failure_on_nonzero_exit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_launchd.Path.home", return_value=fake_home):
            backend = LaunchdBackend(HUB_SPEC)
        with patch("punt_lux._launchctl.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            ok = backend.restart()
        assert ok is False

    def test_systemd_restart_calls_systemctl_restart(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
            backend = SystemdBackend(HUB_SPEC)
        with patch("punt_lux._backend_systemd.subprocess.run") as run:
            run.return_value.returncode = 0
            ok = backend.restart()
        assert run.call_args[0][0] == ["systemctl", "--user", "restart", "luxd-hub"]
        assert ok is True

    def test_systemd_restart_reports_failure_on_nonzero_exit(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._backend_systemd.Path.home", return_value=fake_home):
            backend = SystemdBackend(HUB_SPEC)
        with patch("punt_lux._backend_systemd.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            ok = backend.restart()
        assert ok is False
