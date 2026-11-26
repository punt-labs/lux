"""The menu helper starts a login-shell terminal on the daemon it was given."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.server import PtyServer
from punt_lux.pty.session_starter import SOCKET_ENVIRONMENT, SessionStarter
from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.stream.control import WIRE_VERSION
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.replies import SuccessReply
from punt_lux.wire.stream.session_requests import ListRequest
from tests.pty.wire_client import WireClient

pytestmark = pytest.mark.integration


def test_each_start_creates_a_distinct_session_with_a_default_label(
    daemon: Path,
) -> None:
    starter = SessionStarter(daemon)
    first, second = starter.start(), starter.start()
    client = WireClient(daemon)
    try:
        hello = HelloRequest(1, WIRE_VERSION, snapshot_version())
        assert isinstance(client.request(hello), SuccessReply)
        reply = client.request(ListRequest(2))
        assert isinstance(reply, SuccessReply)
        sessions = reply.result["sessions"]
        assert isinstance(sessions, list)
        assert first != second
        assert {(s["session"], s["label"]) for s in sessions} == {
            (first, "Terminal 1"),
            (second, "Terminal 2"),
        }
    finally:
        client.close()


def test_an_unreachable_daemon_is_an_os_error() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="lxstart-", dir="/tmp") as directory,
        pytest.raises(OSError),
    ):
        SessionStarter(Path(directory) / "none.sock").start()


def test_a_daemon_exports_its_socket_for_the_helper_that_dials_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SOCKET_ENVIRONMENT, "")
    with tempfile.TemporaryDirectory(prefix="lxexp-", dir="/tmp") as directory:
        path = Path(directory) / "pty.sock"
        server = PtyServer(path, idle_timeout=1)
        try:
            assert SessionStarter.local().path == path
        finally:
            server.close()
