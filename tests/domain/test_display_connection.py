"""DisplayConnection -- which dial is current, and every write onto it."""

from __future__ import annotations

import socket
import threading
from typing import Self, final

import pytest

from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
)
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import (
    AckMessage,
    FrameReader,
    PingMessage,
    QueryRequest,
    ReadyMessage,
    SceneMessage,
    encode_message,
)
from punt_lux.protocol.messages.wire_vocabulary import CLIENT_VOCABULARY
from tests.link_access import deaths_of, no_reader


@final
class _Dialer:
    """Dials by handing out one end of a socket pair, counting the dials."""

    dials: int
    peer: socket.socket | None
    ready: ReadyMessage
    fail: bool
    keep: list[socket.socket]

    def __new__(cls, *, fail: bool = False) -> Self:
        self = super().__new__(cls)
        self.dials = 0
        self.peer = None
        self.ready = ReadyMessage()
        self.fail = fail
        self.keep = []
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        self.dials += 1
        if self.fail:
            raise DisplayNotConnectedError("no display")
        ours, self.peer = socket.socketpair()
        self.keep.append(ours.dup())  # holds the stream open past a close()
        return HandshakeResult(sock=ours, endpoint="pair", ready=self.ready)


_BIG = QueryRequest(method="x", params={"blob": "x" * (8 * 1024 * 1024)})


def _opened() -> tuple[DisplayConnection, _Dialer]:
    dialer = _Dialer()
    connection = DisplayConnection(dialer, 1.0, settle_unread=no_reader)
    connection.open()
    return connection, dialer


class TestOpen:
    def test_dials_and_holds_the_socket_and_ready_message(self) -> None:
        connection, dialer = _opened()
        try:
            assert connection.is_open
            assert connection.ready is dialer.ready
        finally:
            connection.close()

    def test_opening_twice_dials_once(self) -> None:
        connection, dialer = _opened()
        try:
            connection.open()
            assert dialer.dials == 1
        finally:
            connection.close()

    def test_a_dial_that_fails_leaves_the_connection_closed(self) -> None:
        connection = DisplayConnection(_Dialer(fail=True), 1.0, settle_unread=no_reader)

        with pytest.raises(DisplayNotConnectedError):
            connection.open()

        assert not connection.is_open
        assert connection.ready is None

    def test_a_new_connection_holds_nothing(self) -> None:
        connection = DisplayConnection(_Dialer(), 1.0, settle_unread=no_reader)

        assert not connection.is_open
        assert not connection.is_open
        assert connection.ready is None


class TestClose:
    def test_releases_the_socket_and_ready_message_together(self) -> None:
        connection, _ = _opened()

        connection.close()

        assert not connection.is_open
        assert not connection.is_open
        assert connection.ready is None

    def test_closing_a_closed_connection_is_not_an_error(self) -> None:
        DisplayConnection(_Dialer(), 1.0, settle_unread=no_reader).close()

    def test_can_be_reopened_after_closing(self) -> None:
        connection, dialer = _opened()
        connection.close()

        connection.open()

        try:
            assert dialer.dials == 2
            assert connection.is_open
        finally:
            connection.close()


class TestRequire:
    def test_returns_the_current_generation(self) -> None:
        connection, _ = _opened()
        try:
            assert connection.require().endpoint == "pair"
        finally:
            connection.close()

    def test_raises_when_never_connected(self) -> None:
        with pytest.raises(
            DisplayNotConnectedError, match="open\\(\\) the display connection"
        ):
            DisplayConnection(_Dialer(), 1.0, settle_unread=no_reader).require()

    def test_a_dial_the_hub_dropped_is_a_hub_retirement_for_whoever_asks_next(
        self,
    ) -> None:
        # The replicator may fetch the dial just as another thread drops it; the
        # display said nothing, so recovery must not blame the batch for it.
        connection, _ = _opened()
        connection.close_if_current(connection.require(), cause="hub")

        with pytest.raises(HubRetiredError):
            connection.require()

    def test_a_connection_never_opened_is_not_a_display_death_either(self) -> None:
        # Nothing was dialed, so there is nothing for the display to have ended: the
        # error is not a closed connection a sender could blame its batch for.
        with pytest.raises(DisplayNotConnectedError) as caught:
            DisplayConnection(_Dialer(), 1.0, settle_unread=no_reader).require()

        assert not isinstance(caught.value, ConnectionClosedError)

    def test_a_dial_the_display_ended_is_a_plain_closed_connection_for_whoever_asks(
        self,
    ) -> None:
        # The reader saw the display die and retired the dial before the sender
        # reached it: the sender still learns the display ended it, so the death is
        # charged to what it was sending.
        connection, _ = _opened()
        connection.close_if_current(connection.require(), cause="display")

        with pytest.raises(ConnectionClosedError) as caught:
            connection.require()

        assert not isinstance(caught.value, HubRetiredError)

    def test_the_cause_is_the_last_retirements(self) -> None:
        connection, _ = _opened()
        connection.close_if_current(connection.require(), cause="display")
        connection.open()
        connection.close()  # the Hub's own close of the next dial

        with pytest.raises(HubRetiredError):
            connection.require()

    def test_a_live_dial_is_returned_whatever_ended_the_one_before(self) -> None:
        connection, _ = _opened()
        connection.close_if_current(connection.require(), cause="display")
        connection.open()

        assert connection.require() is not None

    def test_a_redial_makes_a_new_generation_that_carries_nothing_over(self) -> None:
        connection, _ = _opened()
        first = connection.require()
        first.send_scene(SceneMessage(id="s", elements=[], frame_id="s"))

        connection.close()
        connection.open()
        second = connection.require()
        try:
            assert second is not first
            assert first.owed_acks == 0, "the retired dial's ledger went with it"
            assert second.owed_acks == 0
        finally:
            connection.close()


class TestTheDeathsAConnectionKeeps:
    """Only a display-ended dial that still owed an ack queues a death, once."""

    @staticmethod
    def _owing() -> tuple[DisplayConnection, _Dialer]:
        connection, dialer = _opened()
        connection.require().send_scene(SceneMessage(id="s", elements=[], frame_id="s"))
        return connection, dialer

    def test_a_dial_the_display_ended_with_an_ack_owed_queues_its_ledger(self) -> None:
        connection, dialer = self._owing()
        connection.close_if_current(connection.require(), cause="display")

        (death,) = deaths_of(connection)

        assert death.suspects == frozenset({SceneId("s")})
        assert death.endpoint == "pair"
        if dialer.peer is not None:
            dialer.peer.close()

    def test_a_death_is_handed_over_exactly_once(self) -> None:
        connection, dialer = self._owing()
        connection.close_if_current(connection.require(), cause="display")

        assert len(deaths_of(connection)) == 1
        assert deaths_of(connection) == ()
        if dialer.peer is not None:
            dialer.peer.close()

    def test_a_dial_the_hub_ended_queues_nothing_whatever_it_owed(self) -> None:
        connection, dialer = self._owing()
        connection.close_if_current(connection.require(), cause="hub")

        assert deaths_of(connection) == ()
        if dialer.peer is not None:
            dialer.peer.close()

    def test_the_hubs_own_close_queues_nothing(self) -> None:
        connection, dialer = self._owing()
        connection.close()

        assert deaths_of(connection) == ()
        if dialer.peer is not None:
            dialer.peer.close()

    def test_a_dial_the_display_ended_owing_nothing_queues_nothing(self) -> None:
        connection, dialer = _opened()
        connection.close_if_current(connection.require(), cause="display")

        assert deaths_of(connection) == ()
        if dialer.peer is not None:
            dialer.peer.close()

    def test_each_dial_the_display_ends_queues_its_own_death(self) -> None:
        connection, dialer = self._owing()
        connection.close_if_current(connection.require(), cause="display")
        connection.open()
        connection.require().send_scene(SceneMessage(id="t", elements=[], frame_id="t"))
        connection.close_if_current(connection.require(), cause="display")

        first, second = deaths_of(connection)

        assert first.suspects == frozenset({SceneId("s")})
        assert second.suspects == frozenset({SceneId("t")})
        if dialer.peer is not None:
            dialer.peer.close()


class TestTheLedgerAndTheError:
    def test_a_generation_the_display_ended_owing_an_ack_settles_with_its_ledger(
        self,
    ) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        generation.send_scene(SceneMessage(id="s", elements=[], frame_id="s"))

        settlement = generation.mark_closed("display")

        assert settlement.owed == (SceneId("s"),)
        assert settlement.cause == "display"
        assert not settlement.acked
        if dialer.peer is not None:
            dialer.peer.close()

    def test_the_first_cause_recorded_is_the_one_that_stands(self) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        generation.send_scene(SceneMessage(id="s", elements=[], frame_id="s"))
        generation.end("unresponsive")

        settlement = generation.mark_closed("hub")

        assert settlement.cause == "unresponsive"
        assert settlement.owed == (SceneId("s"),)
        if dialer.peer is not None:
            dialer.peer.close()

    def test_the_error_of_a_dial_still_open_is_refused_not_blamed_on_the_hub(
        self,
    ) -> None:
        connection, dialer = _opened()

        with pytest.raises(ValueError, match="still open"):
            connection.require().closed_error()
        if dialer.peer is not None:
            dialer.peer.close()


class TestThePendingDeathsAreNeverDropped:
    def test_past_the_warning_mark_every_death_is_kept_and_the_queue_says_so(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        connection, dialer = _opened()
        count = 70
        with caplog.at_level("WARNING"):
            for turn in range(count):
                connection.require().send_scene(
                    SceneMessage(id=f"s{turn}", elements=[], frame_id=f"s{turn}")
                )
                connection.close_if_current(connection.require(), cause="display")
                connection.open()

        kept = deaths_of(connection)
        assert len(kept) == count
        assert "wait to be charged" in caplog.text
        connection.close()
        if dialer.peer is not None:
            dialer.peer.close()


class TestCloseIfCurrent:
    def test_retires_the_current_generation(self) -> None:
        connection, _ = _opened()
        generation = connection.require()

        assert connection.close_if_current(generation, cause="hub") is True

        assert not connection.is_open
        assert generation.is_closed

    def test_a_replaced_generation_s_report_changes_nothing(self) -> None:
        connection, _ = _opened()
        stale = connection.require()
        connection.close()
        connection.open()
        replacement = connection.require()
        try:
            assert connection.close_if_current(stale, cause="hub") is False
            assert connection.is_open
            assert not replacement.is_closed
        finally:
            connection.close()

    def test_closing_twice_is_a_no_op_the_second_time(self) -> None:
        connection, _ = _opened()
        generation = connection.require()
        connection.close_if_current(generation, cause="hub")

        assert connection.close_if_current(generation, cause="hub") is False


class TestShutdown:
    def test_a_close_shuts_the_stream_down_even_while_another_handle_holds_it(
        self,
    ) -> None:
        connection, dialer = _opened()
        assert dialer.peer is not None
        dialer.peer.settimeout(2.0)

        connection.close()

        try:
            assert dialer.peer.recv(16) == b""  # EOF: shutdown, not just close
        finally:
            dialer.peer.close()

    def test_a_close_releases_a_sender_wedged_in_sendall(self) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        outcome: list[BaseException] = []

        def wedge() -> None:
            try:
                generation.send(
                    QueryRequest(method="x", params={"blob": "x" * (8 * 1024 * 1024)})
                )
            except OSError as exc:
                outcome.append(exc)

        sender = threading.Thread(target=wedge, daemon=True)
        sender.start()
        sender.join(0.3)
        assert sender.is_alive(), "the peer reads nothing, so the write wedges"

        assert connection.close_if_current(
            generation, cause="hub"
        )  # needs no socket lock

        sender.join(3.0)
        assert not sender.is_alive()
        assert outcome
        if dialer.peer is not None:
            dialer.peer.close()


class TestSend:
    def test_writes_the_encoded_frame_to_the_peer(self) -> None:
        connection, dialer = _opened()
        try:
            connection.require().send(PingMessage(ts=1.5))
            assert dialer.peer is not None
            reader = FrameReader()
            reader.feed(dialer.peer.recv(4096))
            (received,) = reader.drain_typed(CLIENT_VOCABULARY)
            assert received == PingMessage(ts=1.5)
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_send_on_a_retired_generation_raises(self) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        connection.close()

        with pytest.raises(ConnectionClosedError, match="was closed"):
            generation.send(PingMessage())
        if dialer.peer is not None:
            dialer.peer.close()

    def test_a_write_that_raises_ends_its_generation_for_its_reader_to_settle(
        self,
    ) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        assert dialer.peer is not None
        dialer.peer.close()  # the display is gone: the next write fails
        dialer.keep[0].close()

        with pytest.raises(OSError):
            for _ in range(64):
                generation.send(PingMessage())

        assert generation.ended == "display"
        assert connection.is_open  # the dial's reader settles it, not the writer
        connection.close_if_current(generation, cause="display")
        assert not connection.is_open

    def test_a_scene_write_records_the_ack_it_is_owed_after_the_write(self) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        try:
            generation.send_scene(SceneMessage(id="s", elements=[], frame_id="s"))

            assert generation.owed_acks == 1
            generation.deliver(AckMessage(scene_id="s"))
            assert generation.owed_acks == 0
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_second_ping_in_flight_is_refused_and_leaves_the_dial_open(self) -> None:
        # A bookkeeping error before anything was written says nothing of the
        # stream, so it must not retire a healthy dial.
        connection, dialer = _opened()
        generation = connection.require()
        try:
            generation.send_ping(1.0)

            with pytest.raises(RuntimeError, match="already in flight"):
                generation.send_ping(2.0)

            assert not generation.is_closed
            assert connection.is_open
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_scene_write_that_raises_owes_no_ack(self) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        assert dialer.peer is not None
        dialer.peer.close()
        dialer.keep[0].close()

        with pytest.raises(OSError):
            for _ in range(64):
                generation.send_scene(SceneMessage(id="s", elements=[], frame_id="s"))

        assert generation.owed_acks == 0


class TestPollChunk:
    def test_returns_what_the_peer_sent(self) -> None:
        connection, dialer = _opened()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PingMessage(ts=2.0)))
            generation = connection.require()
            assert generation.poll_chunk(1.0) == encode_message(PingMessage(ts=2.0))
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_display_that_closed_the_connection_raises_closed(self) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        try:
            assert dialer.peer is not None
            dialer.peer.close()
            with pytest.raises(ConnectionClosedError, match="closed the connection"):
                generation.poll_chunk(1.0)
        finally:
            connection.close()

    def test_nothing_in_time_is_none_not_a_close(self) -> None:
        connection, dialer = _opened()
        try:
            assert connection.require().poll_chunk(0.05) is None
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_retired_generation_cannot_be_polled_or_written(self) -> None:
        connection, dialer = _opened()
        generation = connection.require()
        connection.close()
        try:
            with pytest.raises(ConnectionClosedError):
                generation.poll_chunk(0.05)
            with pytest.raises(ConnectionClosedError):
                generation.send(PingMessage())
        finally:
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_connection_never_opened_and_one_closed_raise_the_same_error(
        self,
    ) -> None:
        connection, dialer = _opened()
        connection.close()
        try:
            with pytest.raises(ConnectionClosedError):
                connection.require()
        finally:
            if dialer.peer is not None:
                dialer.peer.close()


class TestOpenForListening:
    def test_a_dial_opened_for_listening_is_born_holding_the_reader_slot(self) -> None:
        connection = DisplayConnection(_Dialer(), 1.0, settle_unread=no_reader)

        born = connection.open_listening()

        assert born is connection.require()

        try:
            assert connection.has_reader
            with connection.require().inline_reading() as free:
                assert not free, "an inline read could slip in before the listener"
        finally:
            connection.close()

    def test_open_listening_says_whether_it_dialed(self) -> None:
        connection = DisplayConnection(_Dialer(), 1.0, settle_unread=no_reader)

        connection.open()
        second = connection.open_listening()

        try:
            assert second is None  # the dial already open was not re-made
            assert not connection.has_reader
        finally:
            connection.close()


class TestTheStateLockNeverWaitsOnTheReaderSlot:
    def test_reads_and_retirement_proceed_while_an_inline_read_holds_the_slot(
        self,
    ) -> None:
        # The proven order is request lock, slot, state lock: nothing may take or
        # wait on the slot while holding the state lock.
        connection, _ = _opened()
        generation = connection.require()
        holding = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with generation.inline_reading():
                holding.set()
                release.wait(5.0)

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        assert holding.wait(3.0)
        outcome: list[bool] = []

        def under_the_state_lock() -> None:
            outcome.append(connection.has_reader)
            outcome.append(connection.is_open)
            outcome.append(connection.close_if_current(generation, cause="hub"))

        worker = threading.Thread(target=under_the_state_lock, daemon=True)
        worker.start()
        worker.join(1.0)
        # Judged while the slot is still held: once it is released, a blocked
        # worker finishes too, and the check would prove nothing.
        finished_while_held = not worker.is_alive()
        steps_while_held = list(outcome)
        release.set()
        holder.join(3.0)
        worker.join(3.0)

        assert finished_while_held, "a state-lock step waited on the reader slot"
        assert steps_while_held == [False, True, True]


class TestReaderSlot:
    def test_a_generation_has_one_reader_ever(self) -> None:
        connection, _ = _opened()
        generation = connection.require()
        try:
            assert (generation.claim_reader(), generation.claim_reader()) == (
                True,
                False,
            )
            assert connection.has_reader
        finally:
            connection.close()

    def test_a_new_generation_has_no_reader(self) -> None:
        connection, _ = _opened()
        connection.require().claim_reader()
        connection.close()
        connection.open()
        try:
            assert not connection.has_reader
        finally:
            connection.close()


class TestEndpoint:
    def test_names_the_display_it_is_open_to(self) -> None:
        connection, dialer = _opened()
        try:
            assert connection.endpoint == "pair"
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_says_so_when_not_open(self) -> None:
        assert (
            DisplayConnection(_Dialer(), 1.0, settle_unread=no_reader).endpoint
            == "not connected"
        )
