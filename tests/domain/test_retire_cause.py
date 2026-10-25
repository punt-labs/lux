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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast, final

import pytest

from punt_lux.client_host import UNOBSERVED
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
from punt_lux.domain.hub.dirty_signal import DrainedBatch
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.display_lost import DisplayLostError
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.frame_owner_facts import NoFrameOwnerFacts
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.recovery import SendRecovery
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.protocol import AckMessage, SceneMessage, TextElement, encode_frame
from tests.domain.display_double import Call, Display, until
from tests.link_access import writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.dirty_signal import DirtySignal
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.replicator_ports import (
        CallbackMenuReader,
        ClientProvider,
        DisplayLifecycle,
        MenuReader,
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

        with pytest.raises(OSError, match="fell over"):
            writer_of(link).send_scene(_scene("x"))

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
    def test_after_the_display_ended_the_last_dial_it_names_that_dial(
        self, display: Display
    ) -> None:
        dialer = _SwitchedDialer(display)
        link = DisplayLink(dialer, recv_timeout=3.0)
        link.connect(listen=True)
        dial = link.desk.asks().dial
        display.peer.close()
        assert until(lambda: not link.is_connected)
        dialer.down = True

        with pytest.raises(DisplayLostError) as lost:
            link.connect()

        assert lost.value.dial == dial

    def test_after_the_hub_ended_the_last_dial_it_is_plain_not_connected(
        self, display: Display
    ) -> None:
        dialer = _SwitchedDialer(display)
        link = DisplayLink(dialer, recv_timeout=3.0)
        link.connect()
        link.close()
        dialer.down = True

        with pytest.raises(DisplayNotConnectedError) as caught:
            link.connect()

        assert not isinstance(caught.value, DisplayLostError)

    def test_a_link_that_never_dialed_is_plain_not_connected(
        self, display: Display
    ) -> None:
        dialer = _SwitchedDialer(display)
        dialer.down = True
        link = DisplayLink(dialer, recv_timeout=3.0)

        with pytest.raises(DisplayNotConnectedError) as caught:
            link.connect()

        assert not isinstance(caught.value, DisplayLostError)

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
        assert first != "a dial"


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
class _RetiringClients:
    """A client provider whose link loses its dial right after ``get`` hands it out.

    The race a reader that sees the display die can win: the dial the sender was
    about to use is retired between connecting and writing.
    """

    _link: DisplayLink
    _display: Display
    _gets: int
    _retire_at: int
    __slots__ = ("_display", "_gets", "_link", "_retire_at")

    def __new__(cls, link: DisplayLink, display: Display) -> Self:
        self = super().__new__(cls)
        self._link = link
        self._display = display
        self._gets = 0
        self._retire_at = 0
        return self

    def arm(self, nth: int = 1) -> None:
        """Retire the dial the ``nth`` time the link is handed out from now on."""
        self._retire_at = self._gets + nth

    def get(self) -> DisplayLink:
        link = self._link
        if not link.is_connected:
            link.connect(listen=True)  # a redial, as the registry's get makes
        self._gets += 1
        if self._gets == self._retire_at:
            self._display.peer.close()
            until(lambda: not link.is_connected)
        return link

    def take_writer(self) -> object:
        return self._link.desk.take_seat()

    def drop(self, dial: DialRef) -> None:
        self._link.drop_if_current(dial, cause="hub")


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


@final
class _DyingClients:
    """A client provider whose display dies, and stays down, at its ``nth`` get.

    The reader sees the death and retires the dial before the sender's request is
    made; the redial that ``get`` then makes finds nobody home.
    """

    _link: DisplayLink
    _display: Display
    _dialer: _SwitchedDialer
    _gets: int
    _die_at: int
    __slots__ = ("_dialer", "_die_at", "_display", "_gets", "_link")

    def __new__(
        cls, link: DisplayLink, display: Display, dialer: _SwitchedDialer
    ) -> Self:
        self = super().__new__(cls)
        self._link = link
        self._display = display
        self._dialer = dialer
        self._gets = 0
        self._die_at = 0
        return self

    def arm(self, nth: int = 1) -> None:
        """The display dies at the ``nth`` get from now on."""
        self._die_at = self._gets + nth

    def get(self) -> DisplayLink:
        self._gets += 1
        if self._gets == self._die_at:
            self._dialer.down = True
            self._display.peer.close()
            until(lambda: not self._link.is_connected)
        if not self._link.is_connected:
            self._link.connect(listen=True)  # a redial, as the registry's get makes
        return self._link

    def take_writer(self) -> object:
        return self._link.desk.take_seat()

    def drop(self, dial: DialRef) -> None:
        self._link.drop_if_current(dial, cause="hub")


class _NoLifecycle:
    __slots__ = ()

    def reap(self, timeout: float = 2.0) -> None:
        """Nothing to kill: the display only closed its end."""


def _poison_store(scene: SceneId) -> HubStoreFactory:
    factory = HubStoreFactory()
    owner = ConnectionId("c")
    factory.lifecycle.arrive(owner, UNOBSERVED)
    factory.display.replace_scene(
        Scope.in_process(owner), scene, [TextElement(id="r", content="x")]
    )
    factory.display.frames.record(scene, ScenePresentation(frame_id=str(scene)))
    return factory


@dataclass(frozen=True)
class _Rig:
    """A sender, its recovery and a display that can be taken away."""

    store: HubDisplay
    clients: _DyingClients
    dialer: _SwitchedDialer
    sender: BatchSender
    recovery: SendRecovery


def _rig(display: Display, scene: SceneId, *, isolating: bool = False) -> _Rig:
    factory = _poison_store(scene)
    dialer = _SwitchedDialer(display)
    link = DisplayLink(dialer, recv_timeout=3.0)
    link.connect()
    link.connect(listen=True)
    clients = _DyingClients(link, display, dialer)
    attribution = CrashAttribution(factory.display)
    if isolating:
        attribution.attribute_death(frozenset())  # isolation mode, no scene blamed
    sender = BatchSender(
        factory.display.reader,
        cast("MenuReader", _Menus()),
        cast("CallbackMenuReader", _Menus()),
        cast("ClientProvider", clients),
        link.desk.take_seat(),
        attribution,
        NoFrameOwnerFacts(),
    )
    recovery = SendRecovery(
        cast("ClientProvider", clients),
        cast("DisplayLifecycle", _NoLifecycle()),
        cast("DirtySignal", _Signal()),
        attribution,
        RespawnBackoff(),
    )
    return _Rig(factory.display, clients, dialer, sender, recovery)


def _the_display_stays_down(rig: _Rig, batch: DrainedBatch) -> None:
    """Push the batch again and again: each cycle finds the display still down."""
    for _ in range(ATTRIBUTION_THRESHOLD + 2):
        with pytest.raises(DisplayNotConnectedError) as later:
            rig.sender.push(batch)
        assert not isinstance(later.value, BatchSendError)


class TestADeathTheRedialCouldNotUndo:
    """The display died, the reader saw it, and the redial found nobody home."""

    def test_the_send_is_charged_to_the_scene_it_was_sending(
        self, display: Display
    ) -> None:
        scene = SceneId("s1")
        rig = _rig(display, scene)
        rig.clients.arm()

        with pytest.raises(BatchSendError) as caught:
            rig.sender.push(DrainedBatch(frozenset({scene}), shutting=False))

        assert _is_the_displays_end(caught.value.cause)
        assert caught.value.suspect == frozenset({scene})
        assert caught.value.dial is not None

    def test_the_probe_s_redial_is_charged_to_the_scene_just_sent(
        self, display: Display
    ) -> None:
        scene = SceneId("poison")
        rig = _rig(display, scene, isolating=True)
        rig.clients.arm(nth=2)  # the send's get, then the probe's: the display dies

        with pytest.raises(BatchSendError) as caught:
            rig.sender.push(DrainedBatch(frozenset({scene}), shutting=False))

        assert _is_the_displays_end(caught.value.cause)
        assert caught.value.suspect == frozenset({scene})

    def test_a_display_that_stays_down_is_charged_once_not_every_cycle(
        self, display: Display
    ) -> None:
        scene = SceneId("innocent")
        rig = _rig(display, scene)
        batch = DrainedBatch(frozenset({scene}), shutting=False)
        rig.clients.arm()

        with pytest.raises(BatchSendError) as caught:
            rig.sender.push(batch)
        with pytest.raises(DisplayNotConnectedError):
            rig.recovery.recover(batch, caught.value)  # the heal finds nobody home too
        _the_display_stays_down(rig, batch)

        assert not rig.store.is_quarantined(scene)

    def test_a_death_the_send_itself_found_is_not_charged_again_on_the_redial(
        self, display: Display
    ) -> None:
        scene = SceneId("found-by-the-write")
        rig = _rig(display, scene)
        batch = DrainedBatch(frozenset({scene}), shutting=False)
        rig.dialer.down = True
        display.sockets[-1].fail_next_send = True  # the write itself finds it dead

        with pytest.raises(BatchSendError) as caught:
            rig.sender.push(batch)
        with pytest.raises(DisplayNotConnectedError):
            rig.recovery.recover(batch, caught.value)
        _the_display_stays_down(rig, batch)

        assert not rig.store.is_quarantined(scene)


class TestANewDeathOnANewDialIsChargedAgain:
    """The once-per-death dedupe is per dial, not per scene or per run."""

    def test_the_display_dying_again_on_a_new_dial_is_charged(
        self, display: Display
    ) -> None:
        scene = SceneId("s1")
        rig = _rig(display, scene)
        batch = DrainedBatch(frozenset({scene}), shutting=False)

        rig.clients.arm()
        with pytest.raises(BatchSendError) as first:
            rig.sender.push(batch)  # the death of dial A: charged
        with pytest.raises(DisplayNotConnectedError) as still_down:
            rig.sender.push(batch)  # the display stays down: not charged again
        assert not isinstance(still_down.value, BatchSendError)

        rig.dialer.down = False  # the display returns, on dial B
        rig.clients.get()
        rig.clients.arm()
        with pytest.raises(BatchSendError) as second:
            rig.sender.push(batch)  # the death of dial B: a new death, charged

        assert second.value.suspect == frozenset({scene})
        assert second.value.dial is not None
        assert second.value.dial != first.value.dial


class TestADeathTheReaderSawFirstIsStillAttributed:
    """The reader retires the dial before the send's own write finds it dead."""

    def test_the_send_is_charged_to_the_scene_it_was_sending(
        self, display: Display
    ) -> None:
        factory = HubStoreFactory()
        store = factory.display
        scene = SceneId("s1")
        owner = ConnectionId("c")
        factory.lifecycle.arrive(owner, UNOBSERVED)
        store.replace_scene(
            Scope.in_process(owner), scene, [TextElement(id="r", content="x")]
        )
        store.frames.record(scene, ScenePresentation(frame_id="s1"))
        link = _linked(display)
        clients = _RetiringClients(link, display)
        attribution = CrashAttribution(store)
        sender = BatchSender(
            store.reader,
            cast("MenuReader", _Menus()),
            cast("CallbackMenuReader", _Menus()),
            cast("ClientProvider", clients),
            link.desk.take_seat(),
            attribution,
            NoFrameOwnerFacts(),
        )
        batch = DrainedBatch(frozenset({scene}), shutting=False)
        clients.arm()

        with pytest.raises(BatchSendError) as caught:
            sender.push(batch)

        assert _is_the_displays_end(caught.value.cause)
        assert caught.value.suspect == frozenset({scene})

    def test_a_scene_that_kills_the_display_on_the_probe_is_quarantined(
        self, display: Display
    ) -> None:
        # The isolation loop sends one scene and probes before the next. If the
        # display dies on the scene and the reader sees it before the probe's request
        # is made, each death must still be charged to that scene, so the crash loop
        # reaches the threshold and the scene is quarantined.
        factory = HubStoreFactory()
        store = factory.display
        scene = SceneId("poison")
        owner = ConnectionId("c")
        factory.lifecycle.arrive(owner, UNOBSERVED)
        store.replace_scene(
            Scope.in_process(owner), scene, [TextElement(id="r", content="x")]
        )
        store.frames.record(scene, ScenePresentation(frame_id="poison"))
        link = _linked(display)
        clients = _RetiringClients(link, display)
        attribution = CrashAttribution(store)
        attribution.attribute_death(frozenset())  # isolation mode, no scene blamed
        sender = BatchSender(
            store.reader,
            cast("MenuReader", _Menus()),
            cast("CallbackMenuReader", _Menus()),
            cast("ClientProvider", clients),
            link.desk.take_seat(),
            attribution,
            NoFrameOwnerFacts(),
        )
        recovery = SendRecovery(
            cast("ClientProvider", clients),
            cast("DisplayLifecycle", _NoLifecycle()),
            cast("DirtySignal", _Signal()),
            attribution,
            RespawnBackoff(),
        )
        batch = DrainedBatch(frozenset({scene}), shutting=False)

        for _ in range(ATTRIBUTION_THRESHOLD):
            clients.arm(nth=2)  # the send's get, then the probe's: the display dies
            with pytest.raises(BatchSendError) as caught:
                sender.push(batch)
            assert caught.value.suspect == frozenset({scene})
            recovery.recover(batch, caught.value)

        assert store.is_quarantined(scene)

    def test_recovery_then_counts_the_death(self, display: Display) -> None:
        factory = HubStoreFactory()
        store = factory.display
        scene = SceneId("s1")
        attribution = CrashAttribution(store)
        recovery = SendRecovery(
            cast("ClientProvider", _AlwaysConnected()),
            cast("DisplayLifecycle", _NoLifecycle()),
            cast("DirtySignal", _Signal()),  # the re-marks are not asserted here
            attribution,
            RespawnBackoff(),
        )
        recovery.recover(
            DrainedBatch(frozenset({scene}), shutting=False),
            BatchSendError(
                ConnectionClosedError("the display closed the connection"),
                frozenset({scene}),
                None,
            ),
        )

        assert attribution.mode == "isolating"


@final
class _AlwaysConnected:
    __slots__ = ()

    def get(self) -> object:
        return self


@final
class _Signal:
    __slots__ = ()

    def mark_menus(self) -> None:
        """Unused."""

    def add_all(self, scenes: object) -> None:
        """Unused."""
