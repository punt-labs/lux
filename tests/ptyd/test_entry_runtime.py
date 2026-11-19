"""Terminal startup diagnostics remain useful when stderr is detached."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import TYPE_CHECKING

import pytest

from punt_lux.ptyd.entry_runtime import DaemonOptions, TerminalRuntime

if TYPE_CHECKING:
    from pathlib import Path


def test_daemon_options_read_the_socket_and_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    socket = tmp_path / "terminal.sock"
    monkeypatch.setattr("sys.argv", ["luxd-pty", "--socket", str(socket)])
    monkeypatch.setenv("LUX_PTY_NO_MENU", "1")

    assert DaemonOptions.parse(ArgumentParser()) == DaemonOptions(socket, False)


def test_missing_terminal_extra_logs_a_safe_durable_cause(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_:
        try:
            raise ModuleNotFoundError("private location")
        except ModuleNotFoundError as error:
            TerminalRuntime.start_failed(ArgumentParser(), error)

    assert exit_.value.code == 1
    assert "install punt-lux[terminal]" in capsys.readouterr().err
    assert "Terminal daemon could not start: ModuleNotFoundError" in caplog.text
    assert "private location" not in caplog.text
