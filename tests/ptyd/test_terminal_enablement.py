"""Machine enablement invokes supervisor only by explicit local command."""

from __future__ import annotations

import os
from typing import cast
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.ptyd.service import TerminalService
from punt_lux.service._backend_launchd import LaunchdBackend
from punt_lux.service._backend_systemd import SystemdBackend
from punt_lux.service._backends import pgrep_pid
from punt_lux.service._service_errors import ServiceActionFailedError


@pytest.mark.parametrize(
    ("output", "expected"),
    [("", None), (" \n", None), ("invalid", None), ("123\n456", 123), ("\n123\n", 123)],
)
def test_process_lookup_handles_empty_invalid_and_multiple_results(
    output: str, expected: int | None
) -> None:
    with patch("punt_lux.service._backends.subprocess.run") as run:
        run.return_value.stdout = output
        assert pgrep_pid("luxd-pty") == expected


def test_enable_installs_and_starts_a_stopped_registration() -> None:
    fake = Mock(spec=TerminalService)
    fake.install.return_value = "installed"
    fake.start.return_value = "started"
    fake.is_active = False
    result = TerminalService.enable(cast("TerminalService", fake))
    assert result == "installed\nstarted"
    fake.install.assert_called_once_with()
    fake.start.assert_called_once_with()


def test_repeated_enable_does_not_restart_an_active_owner() -> None:
    fake = Mock(spec=TerminalService)
    fake.install.return_value = "up to date"
    fake.is_active = True
    fake._backend = Mock()
    assert (
        TerminalService.enable(cast("TerminalService", fake))
        == "luxd-pty enabled; running owner left unchanged."
    )
    fake._backend.enable_autostart.assert_called_once_with()
    fake.install.assert_not_called()
    fake.start.assert_not_called()
    fake.restart.assert_not_called()


@pytest.mark.parametrize("backend_type", [SystemdBackend, LaunchdBackend])
@pytest.mark.parametrize("fails", [False, True])
def test_active_owner_enables_login_without_a_restart(
    backend_type: type[SystemdBackend] | type[LaunchdBackend], fails: bool
) -> None:
    fake = Mock(spec=TerminalService)
    fake._backend = backend_type(TerminalService._SPEC)
    fake.is_active = True
    with (
        patch("subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        if fails:
            run.return_value.returncode = 1
            with pytest.raises(ServiceActionFailedError, match="at login"):
                TerminalService.enable(cast("TerminalService", fake))
        else:
            TerminalService.enable(cast("TerminalService", fake))
        assert run.call_count == 1
        args = run.call_args.args[0]
        if backend_type is SystemdBackend:
            assert args == ["systemctl", "--user", "enable", "luxd-pty"]
        else:
            assert args == [
                "launchctl",
                "enable",
                f"gui/{os.getuid()}/com.punt-labs.luxd-pty",
            ]
        assert run.call_args.kwargs == {
            "capture_output": True,
            "text": True,
            "check": False,
        }
    fake.install.assert_not_called()
    fake.start.assert_not_called()


def test_enable_does_not_start_twice_when_install_activates_the_owner() -> None:
    fake = Mock(spec=TerminalService)
    fake.is_active = False

    def install() -> str:
        fake.is_active = True
        return "installed"

    fake.install.side_effect = install
    assert TerminalService.enable(cast("TerminalService", fake)) == "installed"
    fake.install.assert_called_once_with()
    fake.start.assert_not_called()


def test_enable_propagates_install_failure_without_starting() -> None:
    fake = Mock(spec=TerminalService)
    fake.is_active = False
    fake.install.side_effect = OSError("install failed")
    with pytest.raises(OSError, match="install failed"):
        TerminalService.enable(cast("TerminalService", fake))
    fake.start.assert_not_called()


def test_disable_removes_supervisor_registration() -> None:
    fake = Mock(spec=TerminalService)
    fake.uninstall.return_value = "removed"
    assert TerminalService.disable(cast("TerminalService", fake)) == "removed"
    fake.uninstall.assert_called_once_with()


@pytest.mark.parametrize("verb", ["enable", "disable", "restart", "status"])
def test_local_cli_uses_terminal_manager_only(
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
) -> None:
    fake = Mock(spec=TerminalService)
    fake.enable.return_value = "enabled"
    fake.disable.return_value = "disabled"
    fake.restart.return_value = "restarted"
    fake.is_active = False
    monkeypatch.setattr("punt_lux.cli.terminal.TerminalService", lambda: fake)
    result = CliRunner().invoke(app, ["terminal", verb])
    assert result.exit_code == 0, result.output
    if verb == "status":
        fake.enable.assert_not_called()
        fake.install.assert_not_called()
        fake.start.assert_not_called()
    else:
        getattr(fake, verb).assert_called_once_with()
