"""Many named terminals per daemon: create, resume, exit and remove (DES-103)."""

from __future__ import annotations

import re
from typing import Self

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.core import SessionCore, SessionError
from punt_lux.pty.dispatch import SessionDispatch
from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.stream.attach import AttachRequest
from punt_lux.wire.stream.control import WIRE_VERSION
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.replies import FailureReply, SuccessReply
from punt_lux.wire.stream.session_requests import ListRequest
from tests.pty.fake_process import FakeFactory
from tests.pty.peer_link import PeerLink

ID_PATTERN = re.compile(r"t[0-9a-f]+\.\d+")


def test_new_assigns_an_opaque_id_and_the_requested_label() -> None:
    core = SessionCore(FakeFactory())
    try:
        session = core.create(NewRequest(1, "work"))
        assert ID_PATTERN.fullmatch(session.name)
        assert session.label == "work"
    finally:
        core.close()


def test_two_terminals_run_at_once_with_their_own_ids_and_labels() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        first, second = core.create(NewRequest(1)), core.create(NewRequest(2))
        assert first.name != second.name
        assert (first.label, second.label) == ("Terminal 1", "Terminal 2")
        assert len(factory.created) == 2
    finally:
        core.close()


def test_a_duplicate_live_label_is_refused_without_starting_a_shell() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        core.create(NewRequest(1, "work"))
        with pytest.raises(ValueError, match="already in use"):
            core.create(NewRequest(2, "work"))
        assert len(factory.created) == 1
    finally:
        core.close()


def test_a_killed_sessions_label_is_free_again() -> None:
    core = SessionCore(FakeFactory())
    try:
        core.kill(core.create(NewRequest(1, "work")).name)
        assert core.create(NewRequest(2, "work")).label == "work"
    finally:
        core.close()


def test_the_limit_of_sixteen_terminals_is_enforced() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        for number in range(16):
            core.create(NewRequest(number + 1))
        with pytest.raises(SessionError, match="limit"):
            core.create(NewRequest(17))
        assert len(factory.created) == 16
    finally:
        core.close()


def test_ids_are_never_reused() -> None:
    core = SessionCore(FakeFactory())
    try:
        seen: list[str] = []
        for number in range(4):
            session = core.create(NewRequest(number + 1))
            seen.append(session.name)
            core.kill(session.name)
        assert len(set(seen)) == 4
    finally:
        core.close()


def test_attach_resumes_a_running_session_without_spawning() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.create(NewRequest(1))
        assert core.attach(session.name) is session
        assert len(factory.created) == 1
    finally:
        core.close()


def test_attach_of_an_unknown_id_is_refused_and_spawns_nothing() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        with pytest.raises(ValueError, match="unknown session"):
            core.attach("t0.1")
        assert factory.created == []
    finally:
        core.close()


def test_attach_of_an_exited_session_is_refused_and_never_respawns() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.create(NewRequest(1))
        factory.created[0].alive = False
        core.pump()
        with pytest.raises(ValueError, match="unknown session"):
            core.attach(session.name)
        assert len(factory.created) == 1
    finally:
        core.close()


class _Daemon:
    """A dispatch over a fake-process core, with one connected client."""

    factory: FakeFactory
    core: SessionCore
    dispatch: SessionDispatch
    link: PeerLink
    next_id: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.factory = FakeFactory()
        self.core = SessionCore(self.factory)
        self.dispatch = SessionDispatch(self.core)
        self.link = PeerLink()
        self.next_id = 1
        self.ask(HelloRequest(self.take(), WIRE_VERSION, snapshot_version()))
        return self

    def take(self) -> int:
        self.next_id += 1
        return self.next_id

    def ask(self, request: object) -> SuccessReply | FailureReply:
        return self.link.request(self.dispatch, request)  # type: ignore[arg-type]

    def create(self, label: str = "") -> str:
        reply = self.ask(NewRequest(self.take(), label))
        assert isinstance(reply, SuccessReply)
        return str(reply.result["session"])


def test_the_new_reply_carries_the_id_and_label() -> None:
    daemon = _Daemon()
    reply = daemon.ask(NewRequest(9, "work"))
    assert isinstance(reply, SuccessReply)
    assert ID_PATTERN.fullmatch(str(reply.result["session"]))
    assert reply.result["label"] == "work"
    daemon.core.close()


def test_attach_over_the_wire_of_an_unknown_id_is_a_non_retryable_failure() -> None:
    daemon = _Daemon()
    reply = daemon.ask(AttachRequest(9, "t0.1"))
    assert isinstance(reply, FailureReply)
    assert (reply.error, reply.retryable) == ("unknown session t0.1", False)
    assert daemon.factory.created == []
    daemon.core.close()


def test_the_listing_carries_each_sessions_label() -> None:
    daemon = _Daemon()
    daemon.create("work")
    reply = daemon.ask(ListRequest(9))
    assert isinstance(reply, SuccessReply)
    sessions = reply.result["sessions"]
    assert isinstance(sessions, list)
    assert [s["label"] for s in sessions] == ["work"]
    daemon.core.close()
