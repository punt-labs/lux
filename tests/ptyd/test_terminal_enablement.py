"""Machine enablement invokes supervisor only by explicit local command."""

from __future__ import annotations

from typing import cast
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.ptyd.service import TerminalService


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
    assert TerminalService.enable(cast("TerminalService", fake)) == "up to date"
    fake.start.assert_not_called()
    fake.restart.assert_not_called()


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
