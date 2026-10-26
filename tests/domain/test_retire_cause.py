"""Who ended a dial is what the next request learns, and a death is not lost.

A dial the display ended (it closed the stream, a write failed on a reset or wedged
socket, it sent a frame that cannot be decoded) reports a plain
``ConnectionClosedError``, which a sender may blame on what it was sending. A dial
the Hub ended (a query that timed out, a reply out of order, its own close) reports
``HubRetiredError``, which blames nothing. A link that was never opened reports
``DisplayNotConnectedError``. The cause outlives the dial: a request made after the
reader retired the dial still learns who ended it, so a crash is attributed to the
scene that caused it however the retirement raced the send.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast, final

import pytest

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub import batch_sender
from punt_lux.domain.hub.batch_sender import BatchSender, BatchSendError
from punt_lux.domain.hub.clients import ClientRegistry
from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
)
from punt_lux.domain.hub.crash_attribution import (
    ATTRIBUTION_THRESHOLD,
    CrashAttribution,
)
from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.dirty_signal import DrainedBatch
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.display_listener import DisplayListener
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.frame_owner_facts import NoFrameOwnerFacts
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.recovery import SendRecovery
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.protocol import (
    AckMessage,
    PongMessage,
    SceneMessage,
    TextElement,
    encode_frame,
)
from tests.domain.display_double import Call, Display, Responder, until
from tests.link_access import deaths_of, generation_of, writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.batch_sender import _InFlight
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dirty_signal import DirtySignal
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.replicator_ports import (
        CallbackMenuReader,
        ClientProvider,
        DisplayLifecycle,
        MenuReader,
        WriteSeatPort,
    )


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


def _linked(display: Display, *, listening: bool = True) -> DisplayLink:
    link = DisplayLink(display, recv_timeout=3.0)
    link.connect()
    if listening:
        link.connect(listen=True)
    return link


def _scene(scene_id: str) -> SceneMessage:
    return ScenePresentation(frame_id=scene_id).message(scene_id, [])


def _next_request_error(link: DisplayLink) -> BaseException:
    """What a ping made after the dial ended raises."""
    with pytest.raises(OSError) as caught:
        link.desk.asks().ping(timeout=0.2)
    return caught.value


def _is_the_displays_end(error: BaseException) -> bool:
    return isinstance(error, ConnectionClosedError) and not isinstance(
        error, HubRetiredError
    )


class TestADialTheDisplayEnded:
    def test_a_closed_stream_read_by_the_listener(self, display: Display) -> None:
        link = _linked(display)

        display.peer.close()
        assert until(lambda: not link.is_connected)

        assert _is_the_displays_end(_next_request_error(link))

    def test_a_closed_stream_found_by_an_inline_read(self, display: Display) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(1)

        display.peer.close()

        assert pinging.wait()
        assert isinstance(pinging.error, ConnectionClosedError)
        assert _is_the_displays_end(_next_request_error(link))

    def test_a_frame_the_listener_cannot_decode(self, display: Display) -> None:
        link = _linked(display)

        display.peer.send_raw(encode_frame({"type": "ack"}))  # no scene_id
        assert until(lambda: not link.is_connected)

        assert _is_the_displays_end(_next_request_error(link))

    def test_a_frame_an_inline_read_cannot_decode(self, display: Display) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(1)

        display.peer.send_raw(encode_frame({"type": "ack"}))  # no scene_id

        assert pinging.wait()
        assert _is_the_displays_end(pinging.error or ValueError("no error"))
        assert _is_the_displays_end(_next_request_error(link))

    def test_a_write_that_fails_on_the_socket(self, display: Display) -> None:
        link = _linked(display)
        display.sockets[-1].fail_next_send = True

        with pytest.raises(ConnectionClosedError) as raised:
            writer_of(link).send_scene(_scene("x"))

        assert "fell over" in str(raised.value.__cause__)

        assert _is_the_displays_end(_next_request_error(link))


class TestADialTheHubEnded:
    def test_a_query_that_timed_out(self, display: Display) -> None:
        link = _linked(display)

        assert link.desk.asks().query("m", timeout=0.1) is None

        assert isinstance(_next_request_error(link), HubRetiredError)

    def test_a_reply_nobody_was_owed(self, display: Display) -> None:
        link = _linked(display)

        display.peer.send(AckMessage(scene_id="unsolicited"))
        assert until(lambda: not link.is_connected)

        assert isinstance(_next_request_error(link), HubRetiredError)

    def test_a_reply_nobody_was_owed_found_by_an_inline_read(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(1)

        display.peer.send(AckMessage(scene_id="unsolicited"))

        assert pinging.wait()
        assert isinstance(pinging.error, HubRetiredError)
        assert isinstance(_next_request_error(link), HubRetiredError)

    def test_the_hubs_own_close(self, display: Display) -> None:
        link = _linked(display)

        link.close()

        assert isinstance(_next_request_error(link), HubRetiredError)

    def test_a_write_woken_by_the_hubs_retire_is_the_hubs(
        self, display: Display
    ) -> None:
        link = _linked(display)
        generation = generation_of(link)
        wide = ScenePresentation(frame_id="wide").message(
            "wide", [TextElement(id="t", content="x" * 8_000_000)]
        )
        writing = Call(lambda: writer_of(link).send_scene(wide))
        time.sleep(0.2)  # the peer reads nothing: the write is wedged in sendall

        link._connection.retire(generation, cause="hub")

        assert writing.wait()
        assert isinstance(writing.error, HubRetiredError)


class TestADialTheKeepaliveFoundUnresponsive:
    """A dial that is open but does not answer is the display's, not the Hub's."""

    def test_a_write_pinned_to_it_is_charged_to_the_display(
        self, display: Display
    ) -> None:
        link = _linked(display)
        registry = ClientRegistry()
        registry._client = link  # test seam: a registry over a link of our own
        writer = writer_of(link)

        registry.drop_unresponsive(link.desk.asks().dial)

        with pytest.raises(ConnectionClosedError) as caught:
            writer.send_scene(_scene("x"))
        assert _is_the_displays_end(caught.value)

    def test_the_next_request_learns_it_was_the_displays_end(
        self, display: Display
    ) -> None:
        link = _linked(display)
        registry = ClientRegistry()
        registry._client = link  # test seam: a registry over a link of our own

        registry.drop_unresponsive(link.desk.asks().dial)

        assert _is_the_displays_end(_next_request_error(link))

    def test_a_plain_drop_is_still_the_hubs_own(self, display: Display) -> None:
        link = _linked(display)
        registry = ClientRegistry()
        registry._client = link  # test seam: a registry over a link of our own

        registry.drop(link.desk.asks().dial)

        assert isinstance(_next_request_error(link), HubRetiredError)


class TestALinkNeverOpened:
    def test_a_request_raises_not_connected(self, display: Display) -> None:
        link = DisplayLink(display, recv_timeout=3.0)

        with pytest.raises(DisplayNotConnectedError):
            link.desk.asks().ping(timeout=0.1)

    def test_a_writer_raises_not_connected(self, display: Display) -> None:
        link = DisplayLink(display, recv_timeout=3.0)

        with pytest.raises(DisplayNotConnectedError):
            writer_of(link).send_scene(_scene("x"))


class TestARedialThatFindsNobodyHome:
    def test_the_death_outlives_the_redial_that_fails(self, display: Display) -> None:
        dialer = _SwitchedDialer(display)
        link = DisplayLink(dialer, recv_timeout=3.0)
        link.connect(listen=True)
        writer_of(link).send_scene(_scene("s1"))  # written, never acked
        display.peer.close()
        assert until(lambda: not link.is_connected)
        dialer.down = True

        with pytest.raises(DisplayNotConnectedError):
            link.connect()

        (death,) = deaths_of(link)
        assert death.suspects == frozenset({SceneId("s1")})

    def test_after_the_hub_ended_the_last_dial_it_is_plain_not_connected(
        self, display: Display
    ) -> None:
        dialer = _SwitchedDialer(display)
        link = DisplayLink(dialer, recv_timeout=3.0)
        link.connect()
        link.close()
        dialer.down = True

        with pytest.raises(DisplayNotConnectedError):
            link.connect()

        assert deaths_of(link) == ()

    def test_a_link_that_never_dialed_is_plain_not_connected(
        self, display: Display
    ) -> None:
        dialer = _SwitchedDialer(display)
        dialer.down = True
        link = DisplayLink(dialer, recv_timeout=3.0)

        with pytest.raises(DisplayNotConnectedError):
            link.connect()

        assert deaths_of(link) == ()

    def test_two_names_for_one_dial_are_equal_and_two_dials_are_not(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = link.desk.asks().dial
        again = link.desk.asks().dial
        link.close()
        link.connect()

        assert first == again
        assert hash(first) == hash(again)
        assert first != link.desk.asks().dial
        stranger: object = "a dial"
        assert first != stranger


class TestTheCauseFollowsTheLastDial:
    def test_a_redial_replaces_the_cause_with_a_live_dial(
        self, display: Display
    ) -> None:
        link = _linked(display)
        display.peer.close()
        assert until(lambda: not link.is_connected)

        link.connect()

        assert link.desk.asks().dial is not None
        link.close()

    def test_the_cause_is_the_last_retirement_not_the_first(
        self, display: Display
    ) -> None:
        link = _linked(display)
        display.peer.close()
        assert until(lambda: not link.is_connected)
        link.connect()  # a second dial, which the Hub then closes itself
        link.close()

        assert isinstance(_next_request_error(link), HubRetiredError)


@final
class _Menus:
    """An empty agent bar and an empty Clients menu."""

    __slots__ = ()

    def wire_snapshot(self) -> tuple[()]:
        return ()

    def callback_menu_wire(self) -> list[dict[str, object]]:
        return []


@final
class _SwitchedDialer:
    """A display that can be taken away: while ``down``, a dial finds nobody home."""

    _display: Display
    down: bool
    __slots__ = ("_display", "down")

    def __new__(cls, display: Display) -> Self:
        self = super().__new__(cls)
        self._display = display
        self.down = False
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        if self.down:
            msg = "connection refused"
            raise DisplayNotConnectedError(msg)
        return self._display.dial(connect_timeout)


class _NoLifecycle:
    __slots__ = ()

    def reap(self, timeout: float = 2.0) -> None:
        """Nothing to kill: the display only closed its end."""


@final
class _Signal:
    __slots__ = ()

    def mark_menus(self) -> None:
        """Unused."""

    def add_all(self, scenes: object) -> None:
        """Unused."""


def _store(contents: dict[str, str]) -> HubStoreFactory:
    factory = HubStoreFactory()
    owner = ConnectionId("c")
    factory.lifecycle.arrive(owner, UNOBSERVED)
    for scene, content in contents.items():
        factory.display.replace_scene(
            Scope.in_process(owner),
            SceneId(scene),
            [TextElement(id=f"{scene}-root", content=content)],
        )
        factory.display.frames.record(SceneId(scene), ScenePresentation(frame_id=scene))
    return factory


def _mode(rig: _Rig) -> str:
    return rig.attribution.mode


def _batch(*scenes: str) -> DrainedBatch:
    return DrainedBatch(frozenset(SceneId(s) for s in scenes), shutting=False)


@dataclass(frozen=True)
class _Rig:
    """The replicator's parts over the real registry, link and dial model.

    Only the display is scripted. The sender, recovery, attribution, registry, link,
    dials, reader and ack ledgers are the production objects, so a death is found,
    recorded and charged by the code that does it in luxd.
    """

    display: Display
    dialer: _SwitchedDialer
    store: HubDisplay
    registry: ClientRegistry
    link: DisplayLink
    attribution: CrashAttribution
    sender: BatchSender
    recovery: SendRecovery

    def push(self, *scenes: str) -> BatchSendError | None:
        """One replicator cycle: push, and heal a failed send; the failure, if any."""
        batch = _batch(*scenes)
        try:
            self.sender.push(batch)
        except BatchSendError as failure:
            self.recovery.recover(batch, failure)
            return failure
        return None

    def after(self, dials: int) -> None:
        """Wait until the dial made before ``dials`` was ended: found, or redialed."""
        assert until(lambda: not self.link.is_connected or self.display.dials > dials)

    def quarantined(self, scene: str) -> bool:
        return self.store.is_quarantined(SceneId(scene))


def _rig(display: Display, contents: dict[str, str]) -> _Rig:
    factory = _store(contents)
    dialer = _SwitchedDialer(display)
    link = DisplayLink(dialer, recv_timeout=3.0)
    registry = ClientRegistry()
    registry._client = link  # test seam: a registry over a link of our own
    registry.asks()  # the first dial, and its manifest
    attribution = CrashAttribution(factory.display)
    clients = cast("ClientProvider", registry)
    sender = BatchSender(
        factory.display.reader,
        cast("MenuReader", _Menus()),
        cast("CallbackMenuReader", _Menus()),
        clients,
        cast("WriteSeatPort", registry.take_writer()),
        attribution,
        NoFrameOwnerFacts(),
    )
    recovery = SendRecovery(
        clients,
        cast("DisplayLifecycle", _NoLifecycle()),
        cast("DirtySignal", _Signal()),
        RespawnBackoff(),
    )
    return _Rig(
        display,
        dialer,
        factory.display,
        registry,
        link,
        attribution,
        sender,
        recovery,
    )


@pytest.fixture
def poisoned(display: Display) -> Iterator[Responder]:
    responder = Responder(display, frozenset({"p"}))
    yield responder
    responder.stop()


@pytest.fixture
def answering(display: Display) -> Iterator[Responder]:
    responder = Responder(display)
    yield responder
    responder.stop()


class TestADeathDiscoveredByAnyParty:
    """P1 to P4: the dial's own ledger is charged, once, whoever finds it dead."""

    def test_p1_the_replicators_own_send_leaves_the_death_of_the_unacked_scene(
        self, display: Display
    ) -> None:
        rig = _rig(display, {"s1": "x", "s2": "x"})
        rig.push("s1")  # on the wire, never acked
        display.sockets[-1].fail_next_send = True

        failure = rig.push("s2")  # this write finds the display dead
        rig.after(1)  # its reader settles the dial; recovery may redial at once
        assert _mode(rig) == "batching"  # nothing is charged until a push

        rig.sender.charge_deaths()

        assert failure is not None
        assert isinstance(failure.cause, OSError)
        assert rig.attribution.mode == "isolating"  # the ledger was charged

    def test_p1_the_ledger_names_the_written_scene_not_the_one_that_failed(
        self, display: Display
    ) -> None:
        rig = _rig(display, {"s1": "x", "s2": "x"})
        rig.push("s1")
        display.sockets[-1].fail_next_send = True
        with pytest.raises(BatchSendError):
            rig.sender.push(_batch("s2"))
        assert until(lambda: not rig.link.is_connected)  # its reader settles the dial

        (death,) = deaths_of(rig.registry)

        assert death.suspects == frozenset({SceneId("s1")})

    def test_p2_a_poison_scene_is_quarantined_when_another_party_wins_every_redial(
        self, display: Display, poisoned: Responder
    ) -> None:
        # Silent F1: the display crashes a frame after reading the scene, the reader
        # retires the dial, and the keepalive (or a tool) redials it before the
        # replicator looks. The loop must still be broken.
        rig = _rig(display, {"p": "x"})

        for _ in range(ATTRIBUTION_THRESHOLD + 2):
            dials = display.dials
            rig.push("p")
            rig.after(dials)
            rig.registry.asks()  # not the replicator: a probe or a tool's redial
            rig.sender.charge_deaths()  # the replicator's next tick
            if rig.quarantined("p"):
                break

        assert rig.quarantined("p")

    def test_p3_a_death_is_charged_at_discovery_and_the_redial_does_not_recharge_it(
        self, display: Display, poisoned: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        rig.push("p")
        assert until(lambda: not rig.link.is_connected)  # the reader found it

        rig.sender.charge_deaths()  # no redial yet
        assert rig.attribution.mode == "isolating"
        rig.registry.asks()  # a later redial
        rig.sender.charge_deaths()

        assert deaths_of(rig.registry) == ()
        assert not rig.quarantined("p")  # one strike for one death

    def test_p4_two_discoverers_of_one_dial_charge_one_strike_and_a_new_dial_another(
        self, display: Display, poisoned: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        dials = display.dials
        rig.push("p")
        rig.after(dials)
        rig.registry.asks()
        rig.sender.charge_deaths()
        rig.sender.charge_deaths()  # a second party looks at the same dead dial
        assert not rig.quarantined("p")

        dials = display.dials
        rig.push("p")  # the poison scene again, on the new dial
        rig.after(dials)
        rig.registry.asks()
        rig.sender.charge_deaths()

        assert rig.quarantined("p")

    def test_the_next_push_charges_a_death_before_it_sends_anything(
        self,
        display: Display,
        poisoned: Responder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rig = _rig(display, {"p": "x", "q": "x"})
        rig.push("p")
        assert until(lambda: not rig.link.is_connected)  # found; nothing charged yet
        assert rig.attribution.mode == "batching"
        modes: list[str] = []
        real = BatchSender._send_scene

        def spy(self: BatchSender, scene_id: SceneId, flight: _InFlight) -> bool:
            modes.append(rig.attribution.mode)
            return real(self, scene_id, flight)

        monkeypatch.setattr(BatchSender, "_send_scene", spy)

        rig.push("q")

        assert modes
        assert modes[0] == "isolating", "the death was charged after a send"


class TestADeathTheHubEndedChargesNothing:
    """P5: a dial the Hub retired is no evidence, whatever it still owed."""

    def test_p5_a_write_woken_by_the_hubs_retire_charges_nothing(
        self, display: Display
    ) -> None:
        rig = _rig(display, {"s1": "x", "wide": "x" * 8_000_000})
        rig.push("s1")  # written, never acked: the ledger is not empty
        dial = rig.link.desk.asks().dial
        batch = _batch("wide")
        writing = Call(lambda: rig.sender.push(batch))
        time.sleep(0.3)  # the peer reads nothing: the write is wedged in sendall

        rig.registry.drop(dial)  # a query timeout, say: the Hub's own retire

        assert writing.wait()
        failure = writing.error
        assert isinstance(failure, BatchSendError)
        assert isinstance(failure.cause, HubRetiredError)
        rig.recovery.recover(batch, failure)
        assert rig.attribution.mode == "batching"
        assert deaths_of(rig.registry) == ()

    def test_p5_a_ping_waiting_on_the_reader_woken_by_the_hubs_retire_charges_nothing(
        self, display: Display
    ) -> None:
        rig = _rig(display, {"s1": "x"})
        rig.push("s1")
        dial = rig.link.desk.asks().dial
        pinging = Call(lambda: rig.link.desk.asks().ping(timeout=3.0))
        display.peer.read(2)  # the manifest, the scene and the ping are all read

        rig.registry.drop(dial)

        assert pinging.wait()
        assert isinstance(pinging.error, HubRetiredError)
        assert deaths_of(rig.registry) == ()

    def test_p5_an_unlistened_inline_read_woken_by_the_hubs_retire_charges_nothing(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("s1"))  # written, never acked
        dial = link.desk.asks().dial
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(2)  # the scene and the ping are read; the dial reads inline

        link.drop_if_current(dial, cause="hub")

        assert pinging.wait()
        assert isinstance(pinging.error, HubRetiredError)
        assert deaths_of(link) == ()

    def test_a_hub_end_queues_no_death(self, display: Display) -> None:
        link = _linked(display)
        writer_of(link).send_scene(_scene("s1"))

        link.close()  # the Hub's own close of a dial that owed an ack

        assert deaths_of(link) == ()


class TestADeathThatOwedNothing:
    """P6 to P8: the ledger is exactly what was written and never acked."""

    def test_p6_a_stop_while_idle_charges_no_later_scene(
        self, display: Display, answering: Responder
    ) -> None:
        rig = _rig(display, {"s1": "x", "s2": "x"})
        rig.push("s1")
        assert until(lambda: generation_of(rig.link).owed_acks == 0)  # all acked
        dials = display.dials
        display.peer.close()  # a deliberate stop, with nothing in flight
        rig.after(dials)
        rig.registry.asks()

        rig.push("s2")
        rig.sender.charge_deaths()

        assert rig.attribution.mode == "batching"
        assert not rig.quarantined("s2")

    def test_p7_an_acked_scene_is_not_a_suspect(
        self, display: Display, poisoned: Responder
    ) -> None:
        rig = _rig(display, {"a": "x", "p": "x"})
        rig.push("a")
        assert until(lambda: generation_of(rig.link).owed_acks == 0)

        rig.push("p")
        assert until(lambda: not rig.link.is_connected)

        (death,) = deaths_of(rig.registry)
        assert death.suspects == frozenset({SceneId("p")})

    def test_p8_a_scene_written_only_to_a_later_dial_is_not_charged_for_an_earlier(
        self, display: Display, poisoned: Responder
    ) -> None:
        rig = _rig(display, {"p": "x", "b": "x"})
        rig.push("p")
        assert until(lambda: not rig.link.is_connected)
        rig.registry.asks()  # the second dial; "b" is written only to it
        (first,) = deaths_of(rig.registry)
        rig.push("b")
        rig.sender.charge_deaths()

        assert first.suspects == frozenset({SceneId("p")})
        assert rig.attribution.mode == "batching"  # "b" owed nothing at any death
        assert not rig.quarantined("b")


class TestIsolationNarrowsTheSuspects:
    """P9 and P10: after a charge, one scene at a time; a quarantined one never sent."""

    def test_p9_a_death_in_isolation_charges_the_one_scene_in_flight(
        self,
        display: Display,
        poisoned: Responder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rig = _rig(display, {"a": "x", "p": "x"})
        rig.attribution.count_death(frozenset())  # a charge has been made
        charged: list[frozenset[SceneId]] = []
        real = CrashAttribution.count_death

        def spy(self: CrashAttribution, suspect_set: frozenset[SceneId]) -> None:
            charged.append(suspect_set)
            real(self, suspect_set)

        monkeypatch.setattr(CrashAttribution, "count_death", spy)

        dials = display.dials
        rig.push("a", "p")
        rig.after(dials)
        rig.registry.asks()
        rig.sender.charge_deaths()

        assert charged == [frozenset({SceneId("p")})]

    def test_p10_a_quarantined_scene_is_never_sent_again(
        self, display: Display, poisoned: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        for _ in range(ATTRIBUTION_THRESHOLD + 2):
            dials = display.dials
            rig.push("p")
            rig.after(dials)
            rig.registry.asks()
            rig.sender.charge_deaths()
            if rig.quarantined("p"):
                break
        assert rig.quarantined("p")
        seen = len(poisoned.seen)

        rig.push("p")

        assert len(poisoned.seen) == seen


class TestTheLastDial:
    """P11: with nobody to redial, the last dial's death is still charged, once."""

    def test_p11_a_display_that_stays_down_is_charged_once_not_every_cycle(
        self, display: Display, poisoned: Responder
    ) -> None:
        rig = _rig(display, {"p": "x"})
        rig.dialer.down = True
        rig.push("p")
        assert until(lambda: not rig.link.is_connected)

        rig.sender.charge_deaths()
        for _ in range(ATTRIBUTION_THRESHOLD + 2):
            with pytest.raises(DisplayNotConnectedError):
                rig.sender.push(_batch("p"))

        assert rig.attribution.mode == "isolating"  # charged: the display died
        assert not rig.quarantined("p")  # but once, not each cycle it stays down


class TestAnUnackedProbeIsTheDisplaysEnd:
    def test_an_unacked_isolation_probe_leaves_the_death_of_the_scene_sent(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(batch_sender, "_PROBE_TIMEOUT_SECONDS", 0.2)
        rig = _rig(display, {"s1": "x"})  # no responder: nothing is ever acked
        rig.attribution.count_death(frozenset())  # isolation mode

        failure = rig.push("s1")

        assert failure is not None
        assert _is_the_displays_end(failure.cause)
        rig.after(1)  # the dial's reader settles it; recovery may redial at once
        (death,) = deaths_of(rig.registry)  # the unanswering dial's ledger
        assert death.suspects == frozenset({SceneId("s1")})
        assert death.cause == "unresponsive"


class TestAHubRetireThatLandsBetweenTheCheckAndTheRetire:
    """A writer's own retire can lose the race to the Hub's; the Hub's cause stands."""

    @staticmethod
    def _hub_wins_every_display_retire(monkeypatch: pytest.MonkeyPatch) -> None:
        real_end = DisplayConnection._end_by_writer

        def racing_end(
            self: DisplayConnection, generation: DialGeneration, cause: RetireCause
        ) -> bool:
            if cause == "display":  # the Hub's retire lands first
                self.retire(generation, cause="hub")
            return real_end(self, generation, cause)

        monkeypatch.setattr(DisplayConnection, "_end_by_writer", racing_end)

    @staticmethod
    def _hub_asks_before_every_display_record(monkeypatch: pytest.MonkeyPatch) -> None:
        """The Hub's request lands just before each display end is recorded.

        The Hub records no cause, so a request that lands first does not take the
        end from a display that is dead: the display's record is the cause.
        """
        real_end = DialGeneration.end

        def racing_end(self: DialGeneration, cause: RetireCause) -> bool:
            if cause == "display":
                self.request_hub()
            return real_end(self, cause)

        monkeypatch.setattr(DialGeneration, "end", racing_end)

    def test_a_write_that_loses_the_retire_reports_the_hubs_cause_and_queues_nothing(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._hub_wins_every_display_retire(monkeypatch)  # before the dial binds it
        link = _linked(display)
        writer_of(link).send_scene(_scene("s1"))  # owed an ack: a ledger to be charged
        display.sockets[-1].fail_next_send = True

        with pytest.raises(HubRetiredError):
            writer_of(link).send_scene(_scene("s2"))

        assert deaths_of(link) == ()

    def test_an_inline_read_that_cannot_decode_is_the_displays_end_whoever_asked_first(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("s1"))
        self._hub_asks_before_every_display_record(monkeypatch)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(2)

        display.peer.send_raw(encode_frame({"type": "ack"}))  # no scene_id

        assert pinging.wait()
        assert pinging.error is not None
        assert _is_the_displays_end(pinging.error)
        (death,) = deaths_of(link)
        assert death.cause == "display"

    def test_an_inline_decode_failure_logs_the_bad_frame_and_is_the_displays_end(
        self, display: Display, caplog: pytest.LogCaptureFixture
    ) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(1)

        with caplog.at_level(logging.ERROR):
            display.peer.send_raw(encode_frame({"type": "ack"}))  # no scene_id
            assert pinging.wait()

        assert any("malformed frame" in r.getMessage() for r in caplog.records)
        assert any("ack" in r.getMessage() for r in caplog.records)  # its first bytes
        assert pinging.error is not None
        assert _is_the_displays_end(pinging.error)

    def test_a_reply_the_hub_fails_to_route_inline_is_the_hubs_end_not_the_displays(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("s1"))  # owed an ack: a ledger to charge

        def broken(*_args: object, **_kwargs: object) -> None:
            msg = "the Hub's own routing bug"
            raise ValueError(msg)

        monkeypatch.setattr(DisplayListener, "route", broken)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(2)

        display.peer.send(PongMessage(ts=1.0))  # a decoded reply the Hub then mangles

        assert pinging.wait()
        assert isinstance(pinging.error, ValueError)
        assert generation.ended == "hub"
        assert deaths_of(link) == ()  # the display is not charged for the Hub's bug

    def test_an_inline_read_that_finds_the_stream_closed_is_the_displays_end(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("s1"))
        self._hub_asks_before_every_display_record(monkeypatch)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(2)

        display.peer.close()  # the inline read finds the stream closed

        assert pinging.wait()
        assert pinging.error is not None
        assert _is_the_displays_end(pinging.error)
        (death,) = deaths_of(link)
        assert death.cause == "display"
