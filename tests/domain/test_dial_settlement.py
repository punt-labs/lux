"""Dial settlement: one test per partition of ``docs/dial_settlement.tex``.

An ended dial is settled by the holder of its reader slot, after a drain, and by
nobody else but the bound. Each test forces the interleaving one control of the model
reproduces, with two threads where the partition says so, and asserts the settle the
design promises: the dial is not current, the death names the scenes the display never
acked, and nothing waits for a timer that the design does not need. The bound is set
long (``_unbounded``) wherever a timer rescue would hide a stranded dial, and short
where the bound is the thing under test.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import TYPE_CHECKING, Self, cast, final

import pytest

from punt_lux.domain.hub import bounded_ask, dial_socket
from punt_lux.domain.hub.backoff_config import BackoffConfig
from punt_lux.domain.hub.batch_sender import BatchSendError
from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
)
from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.domain.hub.dirty_signal import DirtySignal, DrainedBatch
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.display_listener import DisplayListener
from punt_lux.domain.hub.recovery import SendRecovery
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff
from punt_lux.domain.hub.settler import Settler
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import (
    AckMessage,
    PingMessage,
    PongMessage,
    RemoteEventHandlerInvocation,
    encode_frame,
)
from punt_lux.send_timeout import SEND_TIMEOUT_PACKED
from tests.dial_double import fake_dial
from tests.domain.display_double import Call, Display, FlakySocket, until
from tests.domain.test_ack_attribution import _ids
from tests.domain.test_recovery import _FakeLifecycle, _FakeProvider
from tests.domain.test_retire_cause import _linked, _scene
from tests.link_access import (
    deaths_of,
    drop_route,
    generation_of,
    reading_of,
    writer_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import TracebackType

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.reader_slot import ReaderSlot
    from punt_lux.domain.hub.replicator_ports import ClientProvider, DisplayLifecycle


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


def _unbounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the bound so long that only the design can settle a dial in a test."""
    monkeypatch.setattr(bounded_ask, "SETTLE_BOUND", 60.0)


def _bounded(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    monkeypatch.setattr(bounded_ask, "SETTLE_BOUND", seconds)


def _connected(link: DisplayLink) -> bool:
    """Whether the link has a dial now (a fresh look, so no type is narrowed)."""
    return link.is_connected


def _click() -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(element_id="b", action="click")


def _block_the_listener(link: DisplayLink, display: Display) -> threading.Event:
    """Park the listener thread inside a handler; the event frees it."""
    entered = threading.Event()
    release = threading.Event()

    def handler(_event: RemoteEventHandlerInvocation) -> None:
        entered.set()
        release.wait(10.0)

    link.events.set_fallback_handler(handler)
    display.peer.send(_click())
    assert entered.wait(3.0), "the listener never reached the handler"
    return release


@final
class _SpyCondition:
    """A slot's condition that runs a hook once, just after a critical section ends.

    The hook runs on the thread that left the section, with the lock free: it is the
    interleaving a split critical section would let another thread make.
    """

    _inner: threading.Condition
    hook: Callable[[], None] | None

    def __new__(cls, inner: threading.Condition) -> Self:
        self = super().__new__(cls)
        self._inner = inner
        self.hook = None
        return self

    def __enter__(self) -> bool:
        return self._inner.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._inner.__exit__(exc_type, exc, tb)
        hook, self.hook = self.hook, None
        if hook is not None:
            hook()

    def wait_for(self, predicate: Callable[[], bool]) -> bool:
        return self._inner.wait_for(predicate)

    def notify_all(self) -> None:
        self._inner.notify_all()


class TestAStartThatFails:
    def test_p1_a_dial_ended_before_its_reader_started_is_settled_by_the_release(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = DisplayLink(display, recv_timeout=3.0)
        entered, release = threading.Event(), threading.Event()
        real = DisplayListener.start_on

        def held(listener: DisplayListener, born: DialGeneration) -> None:
            entered.set()
            assert release.wait(5.0)
            real(listener, born)

        monkeypatch.setattr(DisplayListener, "start_on", held)
        opening = Call(lambda: link.connect(listen=True))
        assert entered.wait(3.0)  # the dial is born holding the slot, reader unborn
        generation = generation_of(link)
        generation.send_scene(_scene("a"))
        display.sockets[-1].fail_next_send = True
        failing = Call(lambda: generation.send_scene(_scene("b")))
        assert not failing.wait(0.3)  # refused by the held slot, it waits for it

        release.set()

        assert opening.wait()
        assert isinstance(opening.error, ConnectionClosedError)
        assert failing.wait()
        assert not link.is_connected
        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == ("display", _ids("a"))
        link.connect()  # the next connect redials
        assert _connected(link)
        link.close()

    def test_p2_a_thread_that_cannot_start_leaves_the_slot_free_and_the_dial_gone(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = DisplayLink(display, recv_timeout=3.0)
        real = threading.Thread.start

        def refuse(thread: threading.Thread) -> None:
            if thread.name == "lux-listener":
                msg = "can't start new thread"
                raise RuntimeError(msg)
            real(thread)

        monkeypatch.setattr(threading.Thread, "start", refuse)

        opening = Call(lambda: link.connect(listen=True))

        assert opening.wait(3.0), "the dial waited on a slot nobody would release"
        assert isinstance(opening.error, RuntimeError)
        assert not link.is_connected  # the Hub end settled it on the spot
        monkeypatch.undo()
        link.connect()
        assert _connected(link)
        link.close()


class TestARecordThatLandsInTheSettle:
    @staticmethod
    def _display_ends_after_the_first_drain(
        monkeypatch: pytest.MonkeyPatch, display: Display
    ) -> list[DialGeneration]:
        """After a settle's first look, the display ends the dial and acks ``a``.

        The record is made after the drain began; the ack it sends is in the socket
        only after that drain finished, so a second look is the only one that reads it.
        """
        landed: list[DialGeneration] = []
        real = DialDrain.run

        def run(drain: DialDrain, generation: DialGeneration) -> bool:
            saw = real(drain, generation)
            if not landed:
                landed.append(generation)
                generation.end("display")
                display.peer.send(AckMessage(scene_id="a"))
            return saw

        monkeypatch.setattr(DialDrain, "run", run)
        return landed

    def test_p3_the_listener_that_stops_drains_again_before_it_captures(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        landed = self._display_ends_after_the_first_drain(monkeypatch, display)

        link.close()

        assert landed == [generation]
        assert generation.owed_acks == 0  # the second look read the ack
        assert deaths_of(link) == ()

    def test_p7_a_settle_with_no_reader_drains_again_before_it_captures(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        landed = self._display_ends_after_the_first_drain(monkeypatch, display)

        link.close()

        assert landed == [generation]
        assert generation.owed_acks == 0
        assert deaths_of(link) == ()


class TestAnInlineHolderPastItsLastCheck:
    def test_p4_an_end_that_lands_before_the_release_is_settled_by_it(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        slot = reading_of(link)
        entered, release = threading.Event(), threading.Event()
        real = type(slot)._release
        gated = [False]

        def held_release(this: ReaderSlot, settler: Settler) -> None:
            if not gated[0]:
                gated[0] = True
                entered.set()
                assert release.wait(5.0)
            real(this, settler)

        monkeypatch.setattr(type(slot), "_release", held_release)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        _scene_sent, ping = display.peer.read(2)
        assert isinstance(ping, PingMessage)
        display.peer.send(PongMessage(ts=ping.ts))  # the reply: the inline read is done
        assert entered.wait(3.0)  # past its last look, not yet released
        display.sockets[-1].fail_next_send = True
        failing = Call(lambda: generation.send_scene(_scene("b")))
        assert not failing.wait(0.3), repr(failing.error)  # the inline holder owes it

        release.set()

        assert pinging.wait()
        assert failing.wait()
        assert not link.is_connected
        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == ("display", _ids("a"))


class TestTheCriticalSections:
    def test_p5_a_refusal_and_its_debt_are_one_critical_section(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        slot = reading_of(link)
        hold = slot.claim_for_listener(drop_route)  # a holder, no thread
        assert hold is not None
        spy = _SpyCondition(slot._cond)  # test seam: the slot's lock
        monkeypatch.setattr(slot, "_cond", spy)
        # The holder lets go the instant after the asker's first look at the slot.
        spy.hook = lambda: hold.release(drop_route)

        asking = Call(lambda: link._connection.retire(generation, cause="display"))

        assert asking.wait(2.0), "the debt was left on a slot already released"
        assert not link.is_connected
        (death,) = deaths_of(link)
        assert death.suspects == _ids("a")

    def test_p6_a_release_and_its_debt_read_are_one_critical_section(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        slot = reading_of(link)
        hold = slot.claim_for_listener(drop_route)
        assert hold is not None
        generation.end("display")  # recorded: nobody has asked for a settle yet
        spy = _SpyCondition(slot._cond)
        monkeypatch.setattr(slot, "_cond", spy)
        # An end asks for a settle the instant after the release looked for a debt.
        spy.hook = lambda: slot.ask_settle(drop_route, "display", may_wait=False)

        hold.release(drop_route)

        assert not link.is_connected, "a debt left after the release read it is lost"
        (death,) = deaths_of(link)
        assert death.suspects == _ids("a")


class TestADisplayThatDiesBeforeTheHubEndIsDecided:
    def test_p8_a_display_dead_with_its_ack_ahead_of_the_end_is_the_displays_end(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        display.peer.send(AckMessage(scene_id="a"))
        display.peer.close()  # the end of file is queued behind the ack

        link.close()

        assert generation.ended == "display"  # not the Hub's: the display was dead
        assert generation.owed_acks == 0  # and its ack was read first
        assert deaths_of(link) == ()

    def test_p8_a_display_dead_before_it_acked_is_charged_for_the_scene(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        display.peer.close()  # dead painting a

        link.close()

        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == ("display", _ids("a"))

    def test_p9_a_live_display_asked_to_end_is_the_hubs_end_and_carries_its_scene(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)

        link.close()

        assert generation.ended == "hub"
        assert deaths_of(link) == ()  # carried to the next dial, not charged


class TestAStalledHolder:
    def test_p10_a_hub_end_refuses_at_once_and_is_captured_by_the_bound(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _bounded(monkeypatch, 0.5)
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        release = _block_the_listener(link, display)
        pinging = Call(lambda: link.desk.asks().ping(timeout=5.0))
        display.peer.read(2)  # the scene and the ping

        began = time.monotonic()
        closing = Call(link.close)

        assert pinging.wait(0.4)  # the waiter fails at once, not at the bound
        assert isinstance(pinging.error, HubRetiredError)
        with pytest.raises(HubRetiredError):
            generation.send_scene(_scene("late"))  # writes are refused at once
        assert time.monotonic() - began < 0.5
        assert until(lambda: not link.is_connected)  # captured at the bound
        assert closing.wait()
        link.connect()  # a redial is possible while the holder is still stalled
        assert link.is_connected
        release.set()
        time.sleep(0.3)  # the holder's later settle does nothing
        assert deaths_of(link) == ()
        assert link.is_connected
        link.close()

    @pytest.mark.parametrize("cause", ["display", "unresponsive"])
    def test_p11_a_recorded_end_is_captured_by_the_bound_with_its_cause(
        self, display: Display, monkeypatch: pytest.MonkeyPatch, cause: str
    ) -> None:
        _bounded(monkeypatch, 0.5)
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        release = _block_the_listener(link, display)

        if cause == "display":
            display.sockets[-1].fail_next_send = True
        else:
            display.sockets[-1].time_out_next_send = True
        failing = Call(lambda: generation.send_scene(_scene("b")))

        assert not failing.wait(0.2)  # it waits for the stalled holder
        assert failing.wait(3.0)  # and the bound captures the dial
        assert not link.is_connected
        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == (cause, _ids("a"))
        release.set()
        link.close()

    def test_p12_the_holders_settle_after_the_bound_captured_is_not_a_second_capture(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _bounded(monkeypatch, 0.5)
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        entered, release = threading.Event(), threading.Event()
        real = DialDrain.run

        def held(drain: DialDrain, dial: DialGeneration) -> bool:
            entered.set()
            assert release.wait(5.0)
            return real(drain, dial)

        monkeypatch.setattr(DialDrain, "run", held)
        display.sockets[-1].fail_next_send = True
        failing = Call(lambda: generation.send_scene(_scene("b")))
        assert entered.wait(3.0)  # the listener is in its drain, ahead of its decision

        assert failing.wait(3.0)  # the bound fired and captured
        link.connect()  # a redial: the stalled holder's dial is no longer current
        fresh = generation_of(link)
        assert fresh is not generation
        release.set()  # the listener finishes its settle
        time.sleep(0.3)
        assert link.is_connected, "the stale settle took the redialed dial"
        assert generation_of(link) is fresh
        time.sleep(0.3)

        (death,) = deaths_of(link)  # one capture: one death
        assert death.suspects == _ids("a")
        assert deaths_of(link) == ()
        link.close()


class TestASettleIsOneAndAnEndIsTheFirstRecorded:
    def test_p13_a_recorded_cause_is_never_overridden_by_what_the_drain_sees(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        display.peer.close()  # an end of file is queued

        link._connection.retire(generation, cause="unresponsive")

        assert generation.ended == "unresponsive"
        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == ("unresponsive", _ids("a"))

    def test_p14_a_frame_that_cannot_be_decoded_ends_the_dial_undrained(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        real = Settler.end_stream

        def end_stream(settler: Settler, cause: RetireCause) -> bool:
            # The ack the display sends as the stream is given up on sits unread in
            # the socket: a drain would read it, the undrained end does not.
            display.peer.send(AckMessage(scene_id="a"))
            return real(settler, cause)

        monkeypatch.setattr(Settler, "end_stream", end_stream)

        display.peer.send_raw(encode_frame({"type": "ack"}))  # it cannot be decoded

        assert until(lambda: not link.is_connected)
        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == ("display", _ids("a"))
        assert generation.ended == "display"
        assert deaths_of(link) == ()

    def test_p15_a_settle_made_twice_or_at_once_captures_once(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        hold = reading_of(link).claim_for_listener(drop_route)
        assert hold is not None
        settler = hold.settler
        generation.end("display")
        gate = threading.Barrier(2)

        def settle() -> bool:
            gate.wait(3.0)
            return settler.settle()

        first, second = Call(settle), Call(settle)

        assert first.wait() and second.wait()
        assert sorted([first.result, second.result]) == [False, True]
        assert settler.settle() is False
        (death,) = deaths_of(link)
        assert death.suspects == _ids("a")


class TestAnAskerOnTheHoldersOwnThread:
    def test_the_listeners_own_failed_write_is_settled_on_its_return_not_at_the_bound(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        returned = threading.Event()

        def handler(_event: RemoteEventHandlerInvocation) -> None:
            display.sockets[-1].fail_next_send = True
            try:
                generation.send_scene(_scene("b"))  # fails on the listener thread
            finally:
                returned.set()

        link.events.set_fallback_handler(handler)

        display.peer.send(_click())

        assert returned.wait(2.0), "the holder waited on itself"
        assert until(lambda: not link.is_connected)
        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == ("display", _ids("a"))

    def test_an_inline_holders_own_ask_leaves_a_debt_and_never_waits(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        slot = reading_of(link)

        def hold_and_ask() -> None:
            with slot.inline(drop_route):
                generation.end("display")
                # On the holder's own thread: its debt is enough, a wait could only
                # last out the bound.
                slot.ask_settle(drop_route, "display", may_wait=True)

        holding = Call(hold_and_ask)

        assert holding.wait(3.0), "the holder waited on itself"
        assert holding.error is None
        assert not link.is_connected  # the holder settled the debt as it let go
        (death,) = deaths_of(link)
        assert death.suspects == _ids("a")


class TestTheEndOfAStreamTheDrainSees:
    """O-eof: a reset after queued acks and a plain end of file are both the end."""

    def test_a_reset_that_follows_queued_acks_is_the_displays_end(
        self, display: Display, caplog: pytest.LogCaptureFixture
    ) -> None:
        link = _linked(display, listening=False)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("a"))  # the display never reads it
        display.peer.send(AckMessage(scene_id="a"))  # queued toward the Hub
        display.peer.close()  # closed with the scene unread: a reset follows the ack

        with caplog.at_level(logging.DEBUG):
            link.close()

        assert generation.owed_acks == 0  # the ack was read before the reset
        assert generation.ended == "display"  # and the reset was the end
        assert any("cut short" in r.getMessage() for r in caplog.records)
        assert deaths_of(link) == ()

    def test_a_plain_end_of_file_is_the_displays_end(
        self, display: Display, caplog: pytest.LogCaptureFixture
    ) -> None:
        link = _linked(display, listening=False)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("a"))
        display.peer.read(1)  # the display read it: no reset follows
        display.peer.send(AckMessage(scene_id="a"))
        display.peer.close()

        with caplog.at_level(logging.DEBUG):
            link.close()

        assert generation.owed_acks == 0
        assert generation.ended == "display"
        assert not any("cut short" in r.getMessage() for r in caplog.records)
        assert deaths_of(link) == ()


class TestASendThatTimesOut:
    def test_f5_a_send_timeout_is_recorded_unresponsive_not_the_displays_death(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        generation = generation_of(link)
        display.sockets[-1].time_out_next_send = True

        with pytest.raises(BlockingIOError):
            generation.send_scene(_scene("b"))

        assert generation.ended == "unresponsive"
        (death,) = deaths_of(link)
        assert (death.cause, death.suspects) == ("unresponsive", _ids("a"))


class TestTheWriter:
    """Rule 7: what a write straddling an end records, and what the drain waits for."""

    def test_p17_a_write_that_completes_after_a_hub_request_is_owed_and_carried(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        generation = generation_of(link)
        entered, gate = threading.Event(), threading.Event()
        real = ReplySink.owe_ack

        def parked(this: ReplySink, scene_id: str) -> None:
            entered.set()
            assert gate.wait(5.0)
            real(this, scene_id)

        monkeypatch.setattr(ReplySink, "owe_ack", parked)
        writing = Call(lambda: writer_of(link).send_scene(_scene("a")))
        assert entered.wait(3.0)  # sendall returned; the entry is not yet made
        generation.request_hub()
        gate.set()
        assert writing.wait()

        link._connection.retire(generation, cause="hub")

        assert isinstance(writing.error, HubRetiredError)
        assert generation.ended == "hub"
        assert deaths_of(link) == ()
        assert link._connection._suspects.carried == _ids("a")  # test seam

    def test_p18_a_write_that_fails_after_a_hub_request_records_no_cause(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        generation = generation_of(link)

        def hub_asks_then_fails(_this: FlakySocket, _data: bytes) -> None:
            generation.request_hub()
            msg = "the socket fell over"
            raise OSError(msg)

        monkeypatch.setattr(FlakySocket, "sendall", hub_asks_then_fails)
        with pytest.raises(HubRetiredError):
            generation.send_scene(_scene("a"))

        assert generation.ended is None  # the writer recorded nothing
        display.peer.close()  # the display really died: its end of file is queued
        link._connection.retire(generation, cause="hub")
        assert generation.ended == "display"  # the settle found it, by observing it

    def test_p19_a_drain_waits_for_the_writer_that_holds_the_socket_lock(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("a"))
        holding, release = threading.Event(), threading.Event()
        real = FlakySocket.sendall

        def stand_in(this: FlakySocket, data: bytes) -> None:
            holding.set()
            assert release.wait(5.0)
            real(this, data)

        monkeypatch.setattr(FlakySocket, "sendall", stand_in)
        writing = Call(lambda: generation.send_scene(_scene("b")))
        assert holding.wait(3.0)  # the writer holds the socket lock, mid-send
        display.peer.send(AckMessage(scene_id="a"))  # queued behind the writer
        generation.end("unresponsive")
        settling = Call(
            lambda: link._connection.retire(generation, cause="unresponsive")
        )
        time.sleep(0.1)  # the settler is now waiting for the writer's lock
        # K2: the waiting settler holds neither the state lock nor the sink's.
        probe = Call(lambda: (link._connection.is_open, generation.ended))
        assert probe.wait(0.3), "the waiting settler holds a lock the Hub needs"
        # The writer lets go after the old 0.25 s wait would have given up, and well
        # inside the send timeout.
        threading.Timer(0.5, release.set).start()

        assert settling.wait(5.0)
        assert writing.wait()

        assert all("a" not in death.suspects for death in deaths_of(link))
        assert generation.is_settled

    def test_p20_a_writer_that_never_releases_is_captured_by_the_bound_and_the_drain_says_incomplete(  # noqa: E501
        self,
        display: Display,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _bounded(monkeypatch, 0.3)
        monkeypatch.setattr(dial_socket, "SEND_TIMEOUT_CEILING_SECONDS", 0.2)
        link = _linked(display, listening=False)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("a"))
        holding, release = threading.Event(), threading.Event()
        real = FlakySocket.sendall

        def stand_in(this: FlakySocket, data: bytes) -> None:
            holding.set()
            assert release.wait(10.0)
            real(this, data)

        monkeypatch.setattr(FlakySocket, "sendall", stand_in)
        writing = Call(lambda: generation.send_scene(_scene("b")))
        assert holding.wait(3.0)
        display.peer.send(AckMessage(scene_id="a"))  # readable, behind the writer
        with caplog.at_level(logging.WARNING):
            look = generation.drain()
        assert (look.chunk, look.ended, look.complete) == (b"", False, False)
        assert any("incomplete" in r.getMessage() for r in caplog.records)

        generation.end("unresponsive")
        settling = Call(
            lambda: link._connection.retire(generation, cause="unresponsive")
        )
        try:
            assert settling.wait(5.0)
            assert generation.is_settled  # captured by the bound, undrained
            (death,) = deaths_of(link)
            assert (death.cause, death.suspects) == ("unresponsive", _ids("a"))
        finally:
            release.set()
            writing.wait()

    def test_p21_an_ack_owed_after_the_capture_is_refused_not_recorded(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        generation = generation_of(link)
        real = ReplySink.owe_ack

        def captured_first(this: ReplySink, scene_id: str) -> None:
            generation.end("display")
            link._connection._capture(generation, "display")  # test seam: the door
            real(this, scene_id)

        monkeypatch.setattr(ReplySink, "owe_ack", captured_first)

        with pytest.raises(ConnectionClosedError):
            generation.send_scene(_scene("a"))

        assert generation.owed_acks == 0
        assert deaths_of(link) == ()

    def test_p20_the_captures_shutdown_wakes_a_writer_stuck_in_sendall(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _bounded(monkeypatch, 0.3)
        monkeypatch.setattr(dial_socket, "SEND_TIMEOUT_CEILING_SECONDS", 0.2)
        link = _linked(display, listening=False)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("a"))
        # No send timeout: only the capture's shutdown can end the stuck write.
        display.sockets[-1]._sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_SNDTIMEO, bytes(len(SEND_TIMEOUT_PACKED))
        )
        stuck = threading.Event()

        def jam(this: FlakySocket, _data: bytes) -> None:
            stuck.set()
            this._sock.sendall(b"x" * (64 << 20))  # the peer never reads it

        monkeypatch.setattr(FlakySocket, "sendall", jam)
        writing = Call(lambda: generation.send_scene(_scene("b")))
        assert stuck.wait(3.0)
        display.peer.send(AckMessage(scene_id="a"))  # readable: the drain must wait
        generation.end("unresponsive")
        settling = Call(
            lambda: link._connection.retire(generation, cause="unresponsive")
        )
        try:
            assert settling.wait(5.0)
            assert generation.is_settled
            assert writing.wait(5.0), "the capture left the writer stuck in sendall"
            assert isinstance(writing.error, OSError)
        finally:
            display.peer.close()

    @pytest.mark.parametrize("how", ["capture", "decode_error"])
    def test_p21_a_scene_refused_after_the_capture_is_re_marked_for_the_next_dial(
        self, display: Display, monkeypatch: pytest.MonkeyPatch, how: str
    ) -> None:
        # The writer holds the socket lock across sendall and owe_ack, so a settle by
        # another thread cannot drain: it captures at the bound, undrained. The
        # decode-error variant ends the dial as a frame that cannot be decoded does
        # (the display's end), then settles it from that other thread.
        _bounded(monkeypatch, 0.3)
        monkeypatch.setattr(dial_socket, "SEND_TIMEOUT_CEILING_SECONDS", 0.2)
        link = _linked(display, listening=False)
        generation = generation_of(link)
        real = ReplySink.owe_ack

        def captured_first(this: ReplySink, scene_id: str) -> None:
            if how == "capture":
                generation.end("display")
                link._connection._capture(generation, "display")  # test seam
            else:
                generation.end("display")  # the decode error's end
                Call(lambda: link._connection.retire(generation, cause="display"))
                assert until(lambda: generation.is_settled, 5.0)
            real(this, scene_id)

        monkeypatch.setattr(ReplySink, "owe_ack", captured_first)

        with pytest.raises(ConnectionClosedError) as refused:
            generation.send_scene(_scene("a"))

        signal = DirtySignal()
        SendRecovery(
            cast("ClientProvider", _FakeProvider()),
            cast("DisplayLifecycle", _FakeLifecycle()),
            signal,
            RespawnBackoff(BackoffConfig(clock=lambda: 0.0)),
        ).recover(
            DrainedBatch(frozenset({SceneId("a")}), shutting=False),
            BatchSendError(refused.value, fake_dial()),
        )

        assert SceneId("a") in signal.wait_and_drain(0.0).scenes  # resent next dial
        assert generation.owed_acks == 0  # in no ledger: nothing was charged for it

    def test_p22_a_drain_of_an_unreadable_socket_does_not_wait_for_the_writer(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unbounded(monkeypatch)
        link = _linked(display, listening=False)
        generation = generation_of(link)
        holding, release = threading.Event(), threading.Event()
        real = FlakySocket.sendall

        def stand_in(this: FlakySocket, data: bytes) -> None:
            holding.set()
            assert release.wait(10.0)
            real(this, data)

        monkeypatch.setattr(FlakySocket, "sendall", stand_in)
        writing = Call(lambda: generation.send_scene(_scene("a")))
        assert holding.wait(3.0)  # the writer holds the socket lock, mid-send
        try:
            looking = Call(generation.drain)  # nothing readable: no lock is taken
            assert looking.wait(1.0), "the drain waited for the writer's lock"
            look = looking.result
            assert (look.chunk, look.ended, look.complete) == (b"", False, True)
        finally:
            release.set()
            writing.wait()
