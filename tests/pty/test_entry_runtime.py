"""Terminal startup diagnostics remain useful when stderr is detached."""

from __future__ import annotations

import tempfile
import time
from argparse import ArgumentParser
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.pty.entry_runtime import DaemonOptions, TerminalRuntime

if TYPE_CHECKING:
    from collections.abc import Generator


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


def test_a_normal_stop_is_recorded(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("punt_lux.pty.entry_runtime.process_diagnostics", _quiet)

    @TerminalRuntime.run("daemon", "terminal daemon")
    def _main() -> None:
        pass

    with caplog.at_level("INFO", logger="punt_lux.pty.entry_runtime"):
        _main()

    assert caplog.messages == ["Starting terminal daemon", "Stopped terminal daemon"]


def test_a_failed_run_is_not_recorded_as_a_stop(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("punt_lux.pty.entry_runtime.process_diagnostics", _quiet)

    @TerminalRuntime.run("daemon", "terminal daemon")
    def _main() -> None:
        raise RuntimeError("boom")

    with (
        caplog.at_level("INFO", logger="punt_lux.pty.entry_runtime"),
        pytest.raises(RuntimeError),
    ):
        _main()

    assert "Stopped terminal daemon" not in caplog.messages


def test_an_idle_daemon_records_why_it_stops(caplog: pytest.LogCaptureFixture) -> None:
    from punt_lux.pty.server import PtyServer

    path = Path(tempfile.mkdtemp(prefix="lux-")) / "p.sock"
    server = PtyServer(path, idle_timeout=0.01)
    try:
        with caplog.at_level("INFO", logger="punt_lux.pty.peer_book"):
            deadline = time.monotonic() + 2
            while server.tick() and time.monotonic() < deadline:
                pass
    finally:
        server.close()

    assert caplog.messages == [
        "Terminal daemon idle with no clients or sessions; stopping"
    ]


@contextmanager
def _quiet(_role: str, _name: str) -> Generator[None]:
    yield
