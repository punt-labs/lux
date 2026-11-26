"""The exchange carries requests to the daemon it was given and returns replies."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.daemon_exchange import SOCKET_ENVIRONMENT, DaemonExchange
from punt_lux.pty.server import PtyServer
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.session_requests import KillRequest, ListRequest

pytestmark = pytest.mark.integration


def test_each_new_request_creates_a_distinct_session_with_a_default_label(
    daemon: Path,
) -> None:
    exchange = DaemonExchange(daemon)
    first = str(exchange.ask(NewRequest(2)).result["session"])
    second = str(exchange.ask(NewRequest(2)).result["session"])
    reply = exchange.ask(ListRequest(2))
    sessions = reply.result["sessions"]
    assert isinstance(sessions, list)
    assert first != second
    assert {(s["session"], s["label"]) for s in sessions} == {
        (first, "Terminal 1"),
        (second, "Terminal 2"),
    }


def test_an_unreachable_daemon_is_an_os_error() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="lxstart-", dir="/tmp") as directory,
        pytest.raises(OSError),
    ):
        DaemonExchange(Path(directory) / "none.sock").ask(NewRequest(2))


def test_a_daemon_exports_its_socket_for_the_helper_that_dials_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SOCKET_ENVIRONMENT, "")
    with tempfile.TemporaryDirectory(prefix="lxexp-", dir="/tmp") as directory:
        path = Path(directory) / "pty.sock"
        server = PtyServer(path, idle_timeout=1)
        try:
            assert DaemonExchange.local().path == path
        finally:
            server.close()


def test_a_kill_request_ends_the_session(daemon: Path) -> None:
    exchange = DaemonExchange(daemon)
    session = str(exchange.ask(NewRequest(2)).result["session"])
    exchange.ask(KillRequest(2, session))
    sessions = exchange.ask(ListRequest(2)).result["sessions"]
    assert isinstance(sessions, list)
    assert [s for s in sessions if s.get("state") == "running"] == []
