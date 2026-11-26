"""The held shell is reused while it runs, and every daemon failure is one error."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.current_shell import CurrentShell
from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec, SuccessReply
from tests.pty.scripted_daemon import ScriptedDaemon


def shell(daemon: ScriptedDaemon) -> CurrentShell:
    return CurrentShell(DaemonExchange(daemon.path))


def test_a_refused_new_is_a_session_refusal() -> None:
    refusal = ReplyCodec.encode(FailureReply(2, "terminal session limit reached"))
    with (
        ScriptedDaemon(refusal) as daemon,
        pytest.raises(SessionRefusedError, match="limit"),
    ):
        shell(daemon).obtain()


def test_an_unreadable_reply_is_a_session_refusal() -> None:
    with ScriptedDaemon(b"not json") as daemon, pytest.raises(SessionRefusedError):
        shell(daemon).obtain()


def test_a_reply_without_a_session_is_a_session_refusal() -> None:
    reply = ReplyCodec.encode(SuccessReply(2, {}))
    with (
        ScriptedDaemon(reply) as daemon,
        pytest.raises(SessionRefusedError, match="session"),
    ):
        shell(daemon).obtain()


@pytest.mark.integration
def test_a_held_shell_is_reused_until_it_is_released(daemon: Path) -> None:
    current = CurrentShell(DaemonExchange(daemon))
    first = current.obtain()
    assert current.obtain() == first
    current.release()
    assert current.session == ""
    assert current.obtain() != first
    current.release()
