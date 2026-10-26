"""An ack means a frame survived; suspects outlive a dial; the ledger is read whole.

The display holds a scene's ack until a swap completes (see
``tests/display/test_held_acks.py``), so a scene that crashes the display is unacked
when its dial ends. This pins what the Hub does with that, against the real
registry, link, dials, readers and ack ledgers, and a display that acks at a swap
and can be poisoned:

- T12: the unacked scenes of a dial the Hub ended are carried, and charged when the
  display next dies; an ack read on a later dial clears them.
- T13: a dial the keepalive or the isolation probe gave up on is the display's end for
  charging and is carried as well, since the display may outlive it.
- T14: a display-ended dial is captured by its own reader, after it has read and
  delivered everything the socket held; a discoverer that is not the reader signals.
- O6: the isolation probe releases the next scene on the ack, never on a pong.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub import batch_sender
from punt_lux.domain.hub.batch_sender import BatchSendError
from punt_lux.domain.hub.connection_closed import UnresponsiveError
from punt_lux.domain.hub.display_replies import DisplayReplies
from punt_lux.domain.hub.inbound_router import InboundRouter
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import AckMessage, PingMessage, PongMessage, SceneMessage
from tests.domain.display_double import Call, Display, Responder, until
from tests.domain.test_retire_cause import _linked, _rig, _scene
from tests.link_access import deaths_of, generation_of, writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.reply_sink import Pending
    from punt_lux.protocol import Message


def _ids(*names: str) -> frozenset[SceneId]:
    return frozenset(SceneId(n) for n in names)


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


@pytest.fixture
def swapping(display: Display) -> Iterator[Responder]:
    """A display that acks at a swap the test completes, and dies painting ``p``."""
    responder = Responder(display, frozenset({"p"}), at_swap=True, auto_swap=False)
    yield responder
    responder.stop()


class TestAScenePaintedToDeathIsCharged:
    """P13 and P24: the poison scene is unacked at death, whoever finds the death."""

    def test_p24_the_poison_scene_reaches_quarantine_within_the_threshold(
        self, display: Display
    ) -> None:
        responder = Responder(display, frozenset({"p"}), at_swap=True)  # auto swaps
        rig = _rig(display, {"p": "x", "a": "x"})
        try:
            for _ in range(6):
                dials = display.dials
                rig.push("p", "a")
                rig.after(dials)
                rig.registry.asks()  # not the replicator: a probe or a tool's redial
                rig.sender.charge_deaths()
                if rig.quarantined("p"):
                    break
        finally:
            responder.stop()

        assert rig.quarantined("p")
        assert not rig.quarantined("a")

    def test_p13_a_crash_before_the_swap_leaves_every_installed_scene_unacked(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x", "a": "x"})
        rig.push("a")
        rig.push("p")
        assert until(lambda: swapping.held == ["a", "p"])

        swapping.swap()  # p crashes the swap: no ack is sent

        assert until(lambda: not rig.link.is_connected)
        (death,) = deaths_of(rig.registry)
        assert death.suspects == _ids("a", "p")

    def test_p13_a_crash_after_the_swap_does_not_charge_the_acked_scene(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x", "a": "x"})
        rig.push("a")
        assert until(lambda: swapping.held == ["a"])
        swapping.swap()  # a survives its swap and is acked
        generation = generation_of(rig.link)
        assert until(lambda: generation.owed_acks == 0)
        rig.push("p")
        assert until(lambda: swapping.held == ["p"])

        swapping.swap()  # p crashes its own swap

        assert until(lambda: not rig.link.is_connected)
        (death,) = deaths_of(rig.registry)
        assert death.suspects == _ids("p")


class TestAStalledDisplay:
    """P20 and B3: no swap completes, every scene since the last swap stays unacked."""

    def test_p20_a_death_charges_every_scene_since_the_last_swap_and_none_outside(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"z": "x", "a": "x", "b": "x", "c": "x"})
        rig.push("z")
        assert until(lambda: swapping.held == ["z"])
        swapping.swap()  # z survives its swap
        assert until(lambda: generation_of(rig.link).owed_acks == 0)
        rig.push("a")
        rig.push("b")
        assert until(lambda: swapping.held == ["a", "b"])  # the swaps stop completing

        display.close()  # the display dies; c was never written

        assert until(lambda: not rig.link.is_connected)
        (death,) = deaths_of(rig.registry)
        assert death.suspects == _ids("a", "b")


class TestAnotherHubsCrash:
    """B7: one display, two Hubs: a crash ends both dials and each charges its own."""

    def test_b7_each_hub_charges_its_own_ledger_and_no_more(
        self, display: Display, swapping: Responder
    ) -> None:
        mine = _rig(display, {"a": "x"})
        theirs = _rig(display, {"p": "x"})
        mine.push("a")
        theirs.push("p")
        assert until(lambda: sorted(swapping.held) == ["a", "p"])

        swapping.swap()  # Hub B's scene crashes the display Hub A shares

        assert until(lambda: not mine.link.is_connected)
        assert until(lambda: not theirs.link.is_connected)
        (mine_death,) = deaths_of(mine.registry)
        (theirs_death,) = deaths_of(theirs.registry)
        assert mine_death.suspects == _ids("a")  # struck for a crash it did not cause
        assert theirs_death.suspects == _ids("p")


class TestSuspectsOutliveAHubEndedDial:
    """P16 to P18 and P23: a scene the display holds can crash it on the next dial."""

    def test_p16_the_poison_scene_held_on_a_retired_dial_is_charged_on_the_next(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x", "q": "x"})
        rig.push("p")
        assert until(lambda: swapping.held == ["p"])
        rig.registry.drop(rig.link.desk.asks().dial)  # the Hub's own retire
        rig.registry.asks()
        rig.push("q")
        assert until(lambda: swapping.held == ["p", "q"])

        swapping.swap()  # the display crashes painting p, which it still holds

        assert until(lambda: not rig.link.is_connected)
        (death,) = deaths_of(rig.registry)
        assert death.suspects == _ids("p", "q")

    def test_a_hub_ended_dial_itself_charges_nothing(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        rig.push("p")

        rig.registry.drop(rig.link.desk.asks().dial)

        assert deaths_of(rig.registry) == ()

    def test_p17_an_ack_read_on_a_later_dial_clears_the_carried_set(
        self, display: Display
    ) -> None:
        responder = Responder(display, at_swap=True, auto_swap=False)  # nothing poison
        rig = _rig(display, {"p": "x", "q": "x", "r": "x"})
        try:
            rig.push("p")
            assert until(lambda: responder.held == ["p"])
            rig.registry.drop(rig.link.desk.asks().dial)
            rig.registry.asks()
            rig.push("q")
            assert until(lambda: responder.held == ["p", "q"])
            responder.swap()  # p survived after all; q's ack is read on this dial
            assert until(lambda: generation_of(rig.link).owed_acks == 0)
            rig.push("r")
            assert until(lambda: responder.held == ["r"])

            display.close()  # the display dies for no scene's fault

            assert until(lambda: not rig.link.is_connected)
            (death,) = deaths_of(rig.registry)
            assert death.suspects == _ids("r")  # p was cleared by q's ack
        finally:
            responder.stop()

    @pytest.mark.parametrize("how", ["drop", "close"])
    def test_p18_a_death_with_an_empty_ledger_charges_the_carried_set(
        self, display: Display, swapping: Responder, how: str
    ) -> None:
        rig = _rig(display, {"p": "x"})
        rig.push("p")
        assert until(lambda: swapping.held == ["p"])
        if how == "drop":
            rig.registry.drop(rig.link.desk.asks().dial)
        else:
            rig.link.close()  # the Hub's deliberate close carries the ledger too
        rig.registry.asks()  # the next dial owes nothing

        display.close()

        assert until(lambda: not rig.link.is_connected)
        (death,) = deaths_of(rig.registry)
        assert death.suspects == _ids("p")

    def test_p23_the_carried_set_outlives_a_crash_no_dial_saw(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        rig.push("p")
        assert until(lambda: swapping.held == ["p"])
        rig.registry.drop(rig.link.desk.asks().dial)
        display.close()  # the display dies with no dial live: nobody sees it
        assert deaths_of(rig.registry) == ()
        rig.registry.asks()  # a new display, a new dial that owes nothing

        display.close()

        assert until(lambda: not rig.link.is_connected)
        (death,) = deaths_of(rig.registry)
        assert death.suspects == _ids("p")


class TestAnUnresponsiveDialIsCarriedAndCharged:
    """T13 and P25: the display may outlive a dial the Hub gave up on."""

    def test_p25_a_scene_held_on_an_unresponsive_dial_is_charged_on_the_next_crash(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x", "q": "x"})
        rig.push("p")
        assert until(lambda: swapping.held == ["p"])
        rig.registry.drop_unresponsive(rig.link.desk.asks().dial)  # the keepalive
        assert until(lambda: not rig.link.is_connected)
        (first,) = deaths_of(rig.registry)  # charged at once, as the display's end
        rig.registry.asks()
        rig.push("q")
        assert until(lambda: swapping.held == ["p", "q"])

        swapping.swap()  # the display, still alive, crashes painting p

        assert until(lambda: not rig.link.is_connected)
        (second,) = deaths_of(rig.registry)
        assert first.suspects == _ids("p")
        assert second.suspects == _ids("p", "q")

    def test_a_request_on_an_unresponsive_dial_is_told_the_display_stopped_answering(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        rig.registry.drop_unresponsive(rig.link.desk.asks().dial)
        assert until(lambda: not rig.link.is_connected)

        with pytest.raises(UnresponsiveError):
            rig.link.desk.asks().ping(timeout=0.1)

    def test_an_unresponsive_death_says_the_display_stopped_answering(
        self, display: Display, swapping: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        rig.push("p")
        rig.registry.drop_unresponsive(rig.link.desk.asks().dial)
        assert until(lambda: not rig.link.is_connected)

        (death,) = deaths_of(rig.registry)

        assert death.cause == "unresponsive"
        assert "stopped answering" in death.reason


class _Gate:
    """Holds the reader inside the route of one ack, so the test can race it."""

    entered: threading.Event
    release: threading.Event

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()


def _hold_the_reader_on_the_ack_of(
    monkeypatch: pytest.MonkeyPatch, scene_id: str
) -> _Gate:
    """Make the reader stop with that ack off the socket and not yet applied."""
    gate = _Gate()
    real = InboundRouter.route

    def held_route(
        self: InboundRouter,
        generation: DialGeneration,
        msg: Message,
        *,
        inline: bool = False,
    ) -> None:
        if isinstance(msg, AckMessage) and msg.scene_id == scene_id:
            gate.entered.set()
            assert gate.release.wait(3.0)
        real(self, generation, msg, inline=inline)

    monkeypatch.setattr(InboundRouter, "route", held_route)
    return gate


class TestTheAckInFlightAtRetire:
    """P19 and T14: every ack the display sent is read before the ledger is taken."""

    def test_an_ack_in_the_socket_when_a_non_reader_ends_the_dial_is_not_charged(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        display.peer.send(AckMessage(scene_id="a"))  # sent, and not yet read
        display.sockets[-1].fail_next_send = True

        with pytest.raises(OSError, match="fell over"):
            writer_of(link).send_scene(_scene("b"))

        assert not link.is_connected  # settled by the discoverer: no reader existed
        assert deaths_of(link) == ()

    def test_an_ack_the_reader_has_read_and_not_applied_is_not_charged(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_reader_on_the_ack_of(monkeypatch, "a")
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        display.peer.send(AckMessage(scene_id="a"))
        assert gate.entered.wait(3.0)  # the reader holds the ack: off the socket
        display.sockets[-1].fail_next_send = True

        failing = Call(lambda: writer_of(link).send_scene(_scene("b")))
        assert failing.wait()  # a non-reader found the display dead
        assert deaths_of(link) == (), "a non-reader took the ledger"
        gate.release.set()  # the reader applies the ack, then ends the dial

        assert until(lambda: not link.is_connected)
        assert deaths_of(link) == ()

    def test_an_ack_still_in_the_socket_when_the_reader_settles_is_not_charged(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_reader_on_the_ack_of(monkeypatch, "a")
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        display.peer.send(AckMessage(scene_id="a"))
        assert gate.entered.wait(3.0)
        display.peer.send(AckMessage(scene_id="b"))  # in the socket, not yet read
        display.sockets[-1].fail_next_send = True
        failing = Call(lambda: writer_of(link).send_scene(_scene("c")))
        assert failing.wait()  # the display's end is recorded; the reader is busy

        gate.release.set()  # the reader finishes a, finds the end, drains b

        assert until(lambda: not link.is_connected)
        assert deaths_of(link) == ()

    def test_an_end_recorded_as_an_inline_read_finishes_is_settled_before_it_lets_go(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        real = DisplayReplies._read_inline

        def read_then_end(
            self: DisplayReplies,
            generation: DialGeneration,
            pending: Pending[object, PongMessage],
            deadline: float,
        ) -> PongMessage | None:
            try:
                return real(self, generation, pending, deadline)
            finally:
                generation.end("display")  # a writer's failure lands just after

        monkeypatch.setattr(DisplayReplies, "_read_inline", read_then_end)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        scene, ping = display.peer.read(2)
        assert isinstance(scene, SceneMessage)
        assert isinstance(ping, PingMessage)

        display.peer.send(PongMessage(ts=ping.ts))

        assert pinging.wait()
        assert not link.is_connected  # nobody else would have settled it
        (death,) = deaths_of(link)
        assert death.suspects == _ids("a")

    def test_a_hub_retire_after_a_display_end_leaves_the_ledger_to_the_reader(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_reader_on_the_ack_of(monkeypatch, "a")
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        display.peer.send(AckMessage(scene_id="a"))
        assert gate.entered.wait(3.0)
        display.sockets[-1].fail_next_send = True
        failing = Call(lambda: writer_of(link).send_scene(_scene("c")))
        assert failing.wait()  # the display's end is recorded; the reader is busy
        dial = link.desk.asks().dial

        assert link.drop_if_current(dial, cause="hub") is False  # recovery's drop
        assert deaths_of(link) == (), "the Hub's drop took the ledger unread"
        gate.release.set()

        assert until(lambda: not link.is_connected)
        (death,) = deaths_of(link)
        assert death.suspects == _ids("b")  # a was acked; the reader read it first

    def test_a_scene_whose_ack_never_came_is_still_charged_by_the_reader(
        self, display: Display
    ) -> None:
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        display.peer.close()

        assert until(lambda: not link.is_connected)
        (death,) = deaths_of(link)
        assert death.suspects == _ids("a")


class TestAnIsolationProbeWaitsOnTheAck:
    """O6 and P20/P21: the next scene goes out on an applied ack, never a pong."""

    def test_p21_the_next_scene_is_not_sent_until_the_previous_is_acked(
        self, display: Display
    ) -> None:
        responder = Responder(display, at_swap=True, auto_swap=False)
        rig = _rig(display, {"a": "x", "b": "x"})
        rig.attribution.attribute_death(frozenset())  # a strike: scenes go alone
        try:
            pushing = Call(lambda: rig.push("a", "b"))
            assert until(lambda: len(responder.seen) == 1)
            time.sleep(0.3)  # long enough for a pong to have released the next one

            assert len(responder.seen) == 1, "the probe released on a pong"
            responder.swap()

            assert until(lambda: len(responder.seen) == 2)
            assert until(lambda: responder.held != [])
            responder.swap()
            assert pushing.wait()
        finally:
            responder.stop()

    def test_p21_when_no_ack_comes_the_next_scene_is_not_sent_and_the_dial_is_given_up(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(batch_sender, "_PROBE_TIMEOUT_SECONDS", 0.2)
        responder = Responder(display, at_swap=True, auto_swap=False)
        rig = _rig(display, {"a": "x", "b": "x"})
        rig.attribution.attribute_death(frozenset())
        try:
            failure = rig.push("a", "b")

            assert isinstance(failure, BatchSendError)
            assert len(responder.seen) == 1  # the second scene never went out
            assert until(lambda: not rig.link.is_connected)
            (death,) = deaths_of(rig.registry)  # queued, as the display's end
            assert death.suspects == _ids(responder.seen[0])
            assert death.cause == "unresponsive"
        finally:
            responder.stop()
