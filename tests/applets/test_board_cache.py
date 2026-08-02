"""What a click holds afterwards, and why it is worth holding.

The cache exists for one number: the query behind a board is the whole wait —
one measured click spent 4873 ms of its 4915 ms there — so a board that has been
paid for is kept, and the next click answers with it instead of paying again.

The tests below are about which outcomes are worth keeping. A load that failed
is not: the next click should start cold rather than answer with a red message.
A load that *succeeded* is, whatever became of the push behind it — a Hub that
went away between the query and the round trip has not made the issues any less
read. The two states differ in what a failed load does, so each is driven
through both.

Neither state pushes anything itself. A load returns what is now held, the slot
decides whether to keep it, and only then is the display shown what the slot has
— so the tests drive that whole sequence rather than a state on its own.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.applet_board import AppletBoard
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_slot import BoardSlot
from punt_lux.applets.board_work import BoardWork
from punt_lux.applets.held_board import HeldBoard
from punt_lux.applets.latency import ClickLatency
from punt_lux.applets.no_board import NoBoard
from punt_lux.applets.unreadable_board import UnreadableBoard
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsFailure, BeadsRows

from .board_doubles import ISSUE, Journal, RecordingClient, Source, ThenFails

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    import pytest

    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.operations import RenderTableRequest


@final
class Bench:
    """A slot, the region that shows what it holds, and one click's work.

    A state is only half of what these contracts are about: what a click ends up
    showing depends on the slot the push region reads inside it. So the two are
    built together here, and a test drives a click through them the way the
    service does — load, store, show.
    """

    _board: AppletBoard
    _latency: ClickLatency
    _slot: BoardSlot
    _work: BoardWork
    __slots__ = ("_board", "_latency", "_slot", "_work")

    def __new__(cls, slot: BoardSlot, source: object, client: object) -> Self:
        self = super().__new__(cls)
        self._slot = slot
        load = BoardLoad(BeadsBoard.for_project("lux"), source)  # type: ignore[arg-type]  # structural stand-in
        self._board = AppletBoard(load, slot)
        self._latency = ClickLatency("beads")
        self._work = self._board.work(client, self._latency)  # type: ignore[arg-type]  # structural stand-in
        return self

    @classmethod
    def against(cls, source: Source | ThenFails, client: object) -> Self:
        """One click's work against a stubbed ``bd`` and a recording client."""
        return cls(BoardSlot(), source, client)

    def also(self, source: Source, client: object) -> Bench:
        """A second click against the same board, with its own client and clock."""
        return Bench(self._slot, source, client)

    @property
    def held(self) -> CachedBoard:
        """The state a click answers from, as the slot has it now."""
        return self._board.held

    @property
    def work(self) -> BoardWork:
        """The work a click does: what to load, where to show it, and its clock."""
        return self._work

    def kept(self, cache: CachedBoard) -> Self:
        """Put *cache* in the slot, as a warm-up that loaded it would."""
        self._board.kept(cache)
        return self

    def answering(self) -> AbstractContextManager[None]:
        """Time an answer as the leg times it, so its note lands on that stage."""
        return self._latency.answering()

    def answered(self) -> None:
        """Give the click its visible answer, timed as the leg times it."""
        with self.answering():
            self._board.answers(self._work)

    def serviced(self) -> CachedBoard:
        """Run a click's slow half exactly as the service runs it."""
        loaded = self._board.held.refreshed(self._work)
        self._board.kept(loaded)
        self._board.shows(self._work, loaded)
        return loaded

    def shows(self, mine: CachedBoard) -> None:
        """Offer *mine* to the display, as a click that had loaded it would."""
        self._board.shows(self._work, mine)

    def reported(self) -> None:
        """Log where this click's time went, so the line can be read back."""
        self._latency.report()


def _rows(request: RenderTableRequest) -> list[str]:
    """The issue ids a pushed board is showing."""
    return [str(row[0]) for row in request.rows]


def _shown(cache: CachedBoard, bench: Bench, client: RecordingClient) -> str:
    """What a state puts on the display, as text an assertion can read."""
    cache.shows(bench.work)
    return str(client.scenes[-1].elements)


def test_a_board_that_could_not_be_read_is_not_held() -> None:
    """A red message must not be answered with as though it were a board."""
    client = RecordingClient()
    bench = Bench.against(Source(BeadsFailure("bd: not found")), client)

    cache = bench.serviced()

    assert isinstance(cache, NoBoard)
    assert client.tables == []
    assert "bd: not found" in str(client.scenes[0].elements)
    # And what the slot kept is the state a fresh click starts from, so the next
    # one opens on "Loading issues…" rather than on the last failure.
    assert "Loading issues" in _shown(bench.held, bench, client)


def test_the_reason_a_read_failed_is_held_rather_than_pushed_on_the_spot() -> None:
    """The message goes up the way a board does, or it can land over one.

    A read that fails hands back a state holding the reason; putting that reason
    on screen is then the same act as putting a board there, and the push region
    can refuse it in the one case that matters — a board having arrived while
    the read was failing.
    """
    client = RecordingClient()
    bench = Bench.against(Source(BeadsFailure("bd: not found")), client)

    cache = bench.held.refreshed(bench.work)

    assert client.scenes == []  # the load itself pushed nothing
    assert "bd: not found" in _shown(cache, bench, client)


def test_a_click_from_a_state_that_last_failed_says_so_on_its_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every answer is a few milliseconds; only the line says which was given."""
    client = RecordingClient(frame_is_up=False)
    bench = Bench.against(Source(BeadsRows.of([ISSUE])), client)

    with bench.answering():
        bench.shows(NoBoard(UnreadableBoard("bd: not found")))

    with caplog.at_level(logging.INFO):
        bench.reported()

    assert "(last failure)" in caplog.records[-1].getMessage()
    assert "bd: not found" in str(client.scenes[0].elements)


def test_a_board_that_built_is_held_even_though_its_push_never_landed() -> None:
    """The query is what the cache is for, and a failed push has still paid it.

    A luxd that went away between the query and the round trip used to cost the
    board as well as the push: the failure propagated before the board could be
    stored, so the next click paid the whole multi-second query again — the one
    cost this cache exists to prevent.
    """
    unreachable = RecordingClient(unreachable=True)
    bench = Bench.against(Source(BeadsRows.of([ISSUE])), unreachable)

    assert isinstance(bench.serviced(), HeldBoard)

    # And what it holds is the board that was built, ready to be the next
    # click's answer rather than a placeholder.
    client = RecordingClient(frame_is_up=False)
    bench.also(Source(), client).answered()
    assert _rows(client.tables[0]) == ["lux-1"]


def test_a_push_that_never_landed_says_so_rather_than_vanishing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Holding the board is not the same as pretending the user saw it."""
    client = RecordingClient(unreachable=True)
    bench = Bench.against(Source(BeadsRows.of([ISSUE])), client)

    with caplog.at_level(logging.WARNING):
        bench.serviced()

    assert "not shown" in caplog.text
    assert "luxd is not running" in caplog.text


def test_a_refresh_that_fails_keeps_the_board_already_held() -> None:
    """A board a few minutes old beats a red message where the board was."""
    journal = Journal()
    client = RecordingClient(journal=journal, frame_is_up=False)
    source = ThenFails(BeadsRows.of([ISSUE]), journal)
    bench = Bench.against(source, client)
    load = BoardLoad(BeadsBoard.for_project("lux"), source)

    held = HeldBoard(load.fresh())  # the prefetch's board
    cache = bench.kept(held).serviced()  # the load that fails behind it

    assert cache is held
    assert client.scenes == []  # nothing red replaced it
    # The board it stands over is re-affirmed rather than replaced: what goes up
    # is read from the slot, and the slot is still holding this board.
    assert _rows(client.tables[0]) == ["lux-1"]


def test_a_click_holding_a_board_answers_with_that_board() -> None:
    """The click the whole warm-up is for: the answer is a board, not a word."""
    client = RecordingClient(frame_is_up=False)
    load = BoardLoad(BeadsBoard.for_project("lux"), Source(BeadsRows.of([ISSUE])))
    bench = Bench.against(Source(), client).kept(HeldBoard(load.fresh()))

    bench.answered()

    assert _rows(client.tables[0]) == ["lux-1"]
    assert client.scenes == []


def test_a_board_held_is_pushed_even_when_the_frame_is_already_up() -> None:
    """A raised frame says a board is up; it does not say which board.

    The frame can be standing over issues older than the ones held here — a
    refresh whose push did not land leaves exactly that, since the board is kept
    whatever became of the round trip behind it. Answering such a click with the
    raise alone would leave the older board in front of the user and the newer
    one held but never seen, and the click after it would do the same.
    """
    client = RecordingClient(frame_is_up=True)
    load = BoardLoad(BeadsBoard.for_project("lux"), Source(BeadsRows.of([ISSUE])))
    bench = Bench.against(Source(), client).kept(HeldBoard(load.fresh()))

    bench.answered()

    assert _rows(client.tables[0]) == ["lux-1"]


def test_a_click_holding_nothing_opens_with_the_placeholder() -> None:
    """The cold click: there is no board yet, so the window says what it is doing."""
    client = RecordingClient(frame_is_up=False)
    bench = Bench.against(Source(BeadsRows.of([ISSUE])), client)

    bench.answered()

    assert client.tables == []
    assert "Loading issues" in str(client.scenes[0].elements)


def test_a_click_holding_nothing_leaves_a_frame_that_is_up_alone() -> None:
    """Whatever is in a frame already up is older than nothing at all.

    Holding no board, this state has nothing to put in that frame, and the word
    "Loading" over a board somebody is reading is a loss rather than an answer.
    """
    client = RecordingClient(frame_is_up=True)
    bench = Bench.against(Source(BeadsRows.of([ISSUE])), client)

    bench.answered()

    assert client.scenes == []
    assert client.tables == []
