"""The roster removes every finished session, and acts only on sessions it holds."""

from __future__ import annotations

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.core import SessionCore
from punt_lux.pty.session_roster import SessionRoster
from punt_lux.pty.stream_output import StreamPublisher
from punt_lux.pty.viewers import ViewerBindings
from punt_lux.terminal.output import SessionSnapshot
from punt_lux.wire.stream.frames import FrameKind
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.session_events import SessionEvent
from tests.pty.fake_process import FakeFactory
from tests.pty.peer_link import PeerLink


def test_a_session_whose_io_failed_is_removed_and_announced() -> None:
    factory = FakeFactory()
    core = SessionCore(factory, limit=1)
    bindings = ViewerBindings()
    roster, watcher = SessionRoster(core, bindings), PeerLink()
    roster.watch(watcher.peer)
    session = roster.create(NewRequest(1, "work"))
    factory.created[0].refuse_pump = True
    publisher = StreamPublisher(core, bindings)
    for _ in range(3):
        publisher.pump()
        roster.sweep()
    assert core.describe() == []
    ended = SessionEvent("ended", session.name, "work")
    assert ended in PeerLink.events(watcher.received())
    assert core.create(NewRequest(2, "work")).label == "work"
    core.close()


def test_a_session_in_cleanup_can_be_killed_again() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    roster = SessionRoster(core, ViewerBindings())
    name = roster.create(NewRequest(1, "work")).name
    process = factory.created[0]
    process.reaped = False
    roster.kill(name)
    (pending,) = core.describe()
    assert pending["cleanup_pending"] is True
    process.reaped = True
    roster.kill(name)
    assert core.describe() == []
    core.close()


def test_a_resize_cannot_cut_a_snapshot_after_close_was_sent() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    bindings = ViewerBindings()
    roster, publisher = SessionRoster(core, bindings), StreamPublisher(core, bindings)
    session = roster.create(NewRequest(1, "work"))
    first, second = PeerLink(), PeerLink()
    done = bindings.add(first.peer, session.name, 80, 24)
    stalled = bindings.add(second.peer, session.name, 80, 24)
    done.flow.prepare(session.capture(), session.describe(), initial=True)
    # A snapshot larger than the credit window leaves this viewer with no credit,
    # so its CLOSE cannot be sent and the exited session must stay.
    big = SessionSnapshot(session.name, 0, 80, 24, "test", b"s" * 300_000)
    stalled.flow.prepare(big, session.describe(), initial=True)
    factory.created[0].alive = False
    for _ in range(3):
        publisher.pump()
        roster.sweep()
    assert done.flow.close_sent
    assert not stalled.flow.close_sent
    assert [e["session"] for e in core.describe()] == [session.name]
    first.received()
    publisher.resize(session.name, 100, 30)
    for _ in range(2):
        publisher.pump()
        roster.sweep()
    kinds = [f.kind for f in first.received() if f.channel != 0]
    assert kinds == []
    core.close()


def test_a_refusing_process_group_does_not_stop_the_sweep_and_is_retried() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    roster = SessionRoster(core, ViewerBindings())
    roster.create(NewRequest(1, "work"))
    process = factory.created[0]
    process.alive = False
    process.refuse_close = True
    publisher = StreamPublisher(core, ViewerBindings())
    publisher.pump()
    roster.sweep()
    assert [d["label"] for d in core.describe()] == ["work"]
    process.refuse_close = False
    roster.sweep()
    assert core.describe() == []
    core.close()


def test_a_session_that_failed_in_resize_closes_every_viewer_and_is_removed() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    bindings = ViewerBindings()
    roster, publisher = SessionRoster(core, bindings), StreamPublisher(core, bindings)
    session = roster.create(NewRequest(1, "work"))
    links = [PeerLink(), PeerLink()]
    for link in links:
        binding = bindings.add(link.peer, session.name, 80, 24)
        binding.flow.prepare(session.capture(), session.describe(), initial=True)
    factory.created[0].refuse_resize = True
    with pytest.raises(OSError, match="resize failed"):
        publisher.resize(session.name, 100, 30)
    for _ in range(3):
        publisher.pump()
        roster.sweep()
    closes = [
        [f for f in link.received() if f.kind is FrameKind.CLOSE] for link in links
    ]
    assert [len(c) for c in closes] == [1, 1]
    assert core.describe() == []
    core.close()


def test_a_kill_that_fails_tells_nobody() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    bindings = ViewerBindings()
    roster, watcher, viewer = SessionRoster(core, bindings), PeerLink(), PeerLink()
    roster.watch(watcher.peer)
    session = roster.create(NewRequest(1, "work"))
    binding = bindings.add(viewer.peer, session.name, 80, 24)
    binding.flow.prepare(session.capture(), session.describe(), initial=True)
    watcher.received()
    factory.created[0].refuse_close = True
    with pytest.raises(OSError, match="close failed"):
        roster.kill(session.name)
    assert SessionEvent("ended", session.name, "work") not in PeerLink.events(
        watcher.received()
    )
    StreamPublisher(core, bindings).pump()
    assert [f for f in viewer.received() if f.kind is FrameKind.CLOSE] == []
    factory.created[0].refuse_close = False
    core.close()


def test_killing_an_unknown_session_is_not_retryable() -> None:
    roster = SessionRoster(SessionCore(FakeFactory()), ViewerBindings())
    with pytest.raises(ValueError, match="unknown"):
        roster.kill("t0.99")


def test_attaching_to_a_failed_session_is_not_retryable() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    name = core.create(NewRequest(1, "work")).name
    factory.created[0].refuse_resize = True
    with pytest.raises(OSError, match="resize failed"):
        core.resize(name, 100, 30)
    with pytest.raises(ValueError, match="unknown session"):
        core.attach(name)
    core.close()
