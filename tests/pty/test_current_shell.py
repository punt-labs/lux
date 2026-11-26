"""The held shell is reused while it runs, and every daemon failure is one error."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Self

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.current_shell import CurrentShell
from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.wire.stream.control import ControlRequest
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


def test_a_malformed_frame_from_the_daemon_is_a_session_refusal() -> None:
    header = struct.pack("<IBI", 1, 255, 0)  # a frame kind that does not exist
    with (
        ScriptedDaemon(raw=header) as daemon,
        pytest.raises(SessionRefusedError, match="unreadable"),
    ):
        shell(daemon).obtain()


class SequencedExchange(DaemonExchange):
    """Answer each ask on a fresh scripted daemon with the next payload."""

    _payloads: list[bytes]

    def __new__(cls, *payloads: bytes) -> Self:
        self = super().__new__(cls, Path("unused"))
        self._payloads = list(payloads)
        return self

    def ask(self, request: ControlRequest) -> SuccessReply:
        with ScriptedDaemon(self._payloads.pop(0)) as daemon:
            return DaemonExchange(daemon.path).ask(request)


def listing(*sessions: dict[str, object]) -> bytes:
    return ReplyCodec.encode(SuccessReply(2, {"sessions": list(sessions)}))


def held(*payloads: bytes) -> CurrentShell:
    started = ReplyCodec.encode(SuccessReply(2, {"session": "s1"}))
    current = CurrentShell(SequencedExchange(listing(), started, *payloads))
    assert current.obtain() == "s1"
    return current


def test_a_corrupt_kill_reply_keeps_the_shell_for_a_retry() -> None:
    current = held(b"not json")
    current.release()
    assert current.session == "s1"


def test_a_release_after_a_corrupt_kill_reply_retries_the_kill() -> None:
    current = held(b"not json", ReplyCodec.encode(SuccessReply(2, {})))
    current.release()
    current.release()
    assert current.session == ""


def test_a_kill_refused_as_unknown_forgets_the_shell() -> None:
    current = held(ReplyCodec.encode(FailureReply(2, "no such session")))
    current.release()
    assert current.session == ""


@pytest.mark.parametrize("session", [None, ""])
def test_a_new_reply_with_an_unusable_session_is_refused(session: object) -> None:
    reply = ReplyCodec.encode(SuccessReply(2, {"session": session}))
    current = CurrentShell(SequencedExchange(listing(), reply))
    with pytest.raises(SessionRefusedError, match="without a session"):
        current.obtain()
    assert current.session == ""


RUNNING: dict[str, object] = {"session": "s7", "label": "Terminal", "state": "running"}


def test_a_fresh_shell_adopts_a_running_session_it_started_earlier() -> None:
    current = CurrentShell(SequencedExchange(listing(RUNNING)))  # a new would fail
    assert current.obtain() == "s7"


def test_resume_adopts_a_running_session_it_started_earlier() -> None:
    current = CurrentShell(SequencedExchange(listing(RUNNING)))
    assert current.resume()
    assert current.session == "s7"


def test_a_running_session_under_another_label_is_not_adopted() -> None:
    other: dict[str, object] = RUNNING | {"label": "Build"}
    started = ReplyCodec.encode(SuccessReply(2, {"session": "s8"}))
    current = CurrentShell(SequencedExchange(listing(other), started))
    assert current.obtain() == "s8"


class RecordingExchange(DaemonExchange):
    """Answer list with a fixed listing and new with the daemon's refusal."""

    _listed: bytes
    requests: list[str]

    def __new__(cls, listed: bytes) -> Self:
        self = super().__new__(cls, Path("unused"))
        self._listed = listed
        self.requests = []
        return self

    def ask(self, request: ControlRequest) -> SuccessReply:
        op = str(request.to_dict()["op"])
        self.requests.append(op)
        payload = self._listed
        if op == "new":
            payload = ReplyCodec.encode(
                FailureReply(2, "label 'Terminal' is already in use")
            )
        with ScriptedDaemon(payload) as daemon:
            return DaemonExchange(daemon.path).ask(request)


def test_a_draining_session_holding_the_label_is_never_killed() -> None:
    draining = RUNNING | {"state": "exited"}
    exchange = RecordingExchange(listing(draining))
    current = CurrentShell(exchange)
    assert not current.resume()
    with pytest.raises(SessionRefusedError, match="already in use"):
        current.obtain()
    assert "kill" not in exchange.requests
    assert current.session == ""


@pytest.mark.integration
def test_a_second_shell_over_a_live_daemon_adopts_the_first(daemon: Path) -> None:
    first = CurrentShell(DaemonExchange(daemon))
    started = first.obtain()
    second = CurrentShell(DaemonExchange(daemon))
    assert second.obtain() == started
    first.release()
