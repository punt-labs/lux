"""A Hub end is atomic with its cause, and only a dial's reader captures a display end.

A dial's end has two phases: the cause is recorded (first wins), then the reader reads
what the socket still holds and takes the ledger. The Hub's own end is both phases at
once, but it may take the ledger only if the cause it recorded is the one that stands.
Each test below forces one interleaving a check-then-act Hub end loses, with two
threads, and asserts the death is charged to the scenes the display never acked:

- a display end landing between the Hub's decision and its end;
- the reader found the end of file and is draining when the Hub ends the dial;
- ``stop`` and ``close`` racing an end somebody already recorded.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
)
from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import AckMessage
from tests.domain.display_double import Call, Display, until
from tests.domain.test_ack_attribution import (
    _Gate,
    _hold_the_reader_on_the_ack_of,
    _ids,
)
from tests.domain.test_retire_cause import _linked, _scene
from tests.link_access import deaths_of, generation_of, writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


def _the_display_lands_before_the_first_hub_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make a display end win the sink just before the first Hub end reaches it.

    Whatever decision the Hub took before it ended the dial, the display's end was
    recorded after it and before the Hub's own: the first cause stands.
    """
    real = ReplySink.end
    armed = [True]

    def racing(self: ReplySink, cause: RetireCause) -> bool:
        if cause == "hub" and armed[0]:
            armed[0] = False
            real(self, "display")
        return real(self, cause)

    monkeypatch.setattr(ReplySink, "end", racing)


def _hold_the_drain(monkeypatch: pytest.MonkeyPatch) -> _Gate:
    """Park the reader inside its drain, after it has found the end."""
    gate = _Gate()
    real = DialDrain.run

    def held(self: DialDrain, generation: DialGeneration) -> None:
        gate.entered.set()
        assert gate.release.wait(3.0)
        real(self, generation)

    monkeypatch.setattr(DialDrain, "run", held)
    return gate


class TestAHubEndThatLosesTheCauseLeavesTheLedgerToTheReader:
    def test_a_display_end_landing_in_the_hub_retire_with_a_reader_busy(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_reader_on_the_ack_of(monkeypatch, "a")
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        display.peer.send(AckMessage(scene_id="a"))
        assert gate.entered.wait(3.0)  # the reader holds ack a, off the socket
        display.peer.send(AckMessage(scene_id="b"))  # in the socket, unread
        dial = link.desk.asks().dial
        _the_display_lands_before_the_first_hub_end(monkeypatch)

        link.drop_if_current(dial, cause="hub")  # a query's give-up, say

        assert deaths_of(link) == (), "the Hub's end took the ledger unread"
        gate.release.set()
        assert until(lambda: not link.is_connected)
        assert deaths_of(link) == ()  # a was applied, b drained: nothing is owed

    def test_a_display_end_landing_in_the_hub_retire_with_no_reader(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        display.peer.send(AckMessage(scene_id="a"))  # sent, and not yet read
        dial = link.desk.asks().dial
        _the_display_lands_before_the_first_hub_end(monkeypatch)

        link.drop_if_current(dial, cause="hub")

        assert not link.is_connected  # settled by the one who found no reader
        assert deaths_of(link) == ()  # the discoverer drained a's ack first

    def test_a_display_end_the_unread_settle_charges_when_nothing_was_acked(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        dial = link.desk.asks().dial
        _the_display_lands_before_the_first_hub_end(monkeypatch)

        link.drop_if_current(dial, cause="hub")

        (death,) = deaths_of(link)
        assert death.cause == "display"
        assert death.suspects == _ids("a")


class TestADisplayEndIsRecordedWhenTheReaderSeesIt:
    def test_a_hub_retire_in_the_readers_drain_does_not_make_the_death_a_hub_end(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_drain(monkeypatch)
        link = _linked(display)
        writer_of(link).send_scene(_scene("p"))  # the poison scene, never acked
        dial = link.desk.asks().dial

        display.peer.close()  # the display dies painting it
        assert gate.entered.wait(3.0)  # the reader saw the end and is draining

        link.drop_if_current(dial, cause="hub")  # an MCP query gives up right now
        gate.release.set()

        assert until(lambda: not link.is_connected)
        (death,) = deaths_of(link)
        assert death.cause == "display"
        assert death.suspects == _ids("p")

    def test_a_hub_retire_in_an_inline_readers_drain_does_not_make_it_a_hub_end(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_drain(monkeypatch)
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("p"))
        dial = link.desk.asks().dial
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(2)  # the scene and the ping: the dial reads inline

        display.peer.close()  # the display dies painting p
        assert gate.entered.wait(3.0)  # the inline reader saw it and is draining

        link.drop_if_current(dial, cause="hub")
        gate.release.set()

        assert pinging.wait()
        (death,) = deaths_of(link)
        assert death.cause == "display"
        assert death.suspects == _ids("p")

    def test_the_end_is_on_the_dial_before_the_drain_begins(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_drain(monkeypatch)
        link = _linked(display)
        generation = generation_of(link)

        display.peer.close()
        assert gate.entered.wait(3.0)

        assert generation.ended == "display"
        gate.release.set()


class TestAnInlineReaderThatLosesTheEndReportsTheWinnersCause:
    def test_a_reply_nobody_was_owed_when_the_display_ended_it_first(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(1)
        _the_display_lands_before_the_first_hub_end(monkeypatch)

        display.peer.send(AckMessage(scene_id="unsolicited"))

        assert pinging.wait()
        assert isinstance(pinging.error, ConnectionClosedError)
        assert not isinstance(pinging.error, HubRetiredError)


class TestAStopOrCloseRacingAnEndSomebodyRecorded:
    def test_stop_does_not_take_the_ledger_of_a_dial_a_writer_ended(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = _hold_the_reader_on_the_ack_of(monkeypatch, "a")
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        display.peer.send(AckMessage(scene_id="a"))
        assert gate.entered.wait(3.0)
        display.peer.send(AckMessage(scene_id="b"))  # in the socket, unread
        display.sockets[-1].fail_next_send = True
        failing = Call(lambda: writer_of(link).send_scene(_scene("c")))
        assert failing.wait()  # the display's end is recorded; the reader is busy

        closing = Call(link.close)  # stop joins the reader, which is parked
        time.sleep(0.3)
        assert deaths_of(link) == (), "stop took the ledger before the reader drained"
        gate.release.set()

        assert closing.wait()
        assert deaths_of(link) == ()

    def test_close_does_not_take_the_ledger_of_a_dial_nobody_read(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        display.peer.send(AckMessage(scene_id="a"))  # sent, and not yet read
        generation_of(link).end("display")  # recorded, and nobody has settled it

        link.close()

        assert deaths_of(link) == ()  # the ack was read before the ledger was taken


_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux" / "domain" / "hub"


def _calls_to(source: str, name: str) -> int:
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    )


class TestOnlyAReaderTakesTheLedgerOfADisplayEnd:
    """The Hub's ends go through ``retire``; ``close_if_current`` is a reader's door."""

    def test_close_if_current_is_called_only_by_a_dials_readers(self) -> None:
        callers = {
            path.stem
            for path in _SRC.glob("*.py")
            if _calls_to(path.read_text(), "close_if_current") > 0
        }

        assert callers == {"dial_reader", "display_listener", "display_replies"}

    def test_a_planted_hub_side_capture_is_counted(self) -> None:
        planted = "def f(connection, g):\n    connection.close_if_current(g)\n"

        assert _calls_to(planted, "close_if_current") == 1

    def test_the_hub_side_ends_all_retire(self) -> None:
        names = {
            path.stem
            for path in _SRC.glob("*.py")
            if _calls_to(path.read_text(), "retire") > 0
        }

        assert {"display_link", "listener_thread", "display_connection"} <= names


def test_the_scene_ids_these_tests_name_are_scene_ids() -> None:
    assert SceneId("a") in _ids("a")
