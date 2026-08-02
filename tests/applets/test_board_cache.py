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
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_work import BoardWork
from punt_lux.applets.held_board import HeldBoard
from punt_lux.applets.latency import ClickLatency
from punt_lux.applets.no_board import NoBoard
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsFailure, BeadsRows
from punt_lux.operations import RenderTableRequest

from .board_doubles import ISSUE, Journal, RecordingClient, Source, ThenFails

if TYPE_CHECKING:
    import pytest


def _work(source: Source | ThenFails, client: object) -> BoardWork:
    """One click's work against a stubbed ``bd`` and a recording client.

    The stand-in client is structural, so the one cast these tests need lives
    here rather than on every call.
    """
    return BoardWork(
        BoardLoad(BeadsBoard.for_project("lux"), source),
        client,  # type: ignore[arg-type]  # structural stand-in
        ClickLatency("beads"),
    )


def _rows(request: RenderTableRequest) -> list[str]:
    """The issue ids a pushed board is showing."""
    return [str(row[0]) for row in request.rows]


def test_a_board_that_could_not_be_read_is_not_held() -> None:
    """A red message must not be answered with as though it were a board."""
    client = RecordingClient()
    cache = NoBoard().refreshed(_work(Source(BeadsFailure("bd: not found")), client))

    assert isinstance(cache, NoBoard)
    assert client.tables == []
    assert "bd: not found" in str(client.scenes[0].elements)


def test_a_board_that_built_is_held_even_though_its_push_never_landed() -> None:
    """The query is what the cache is for, and a failed push has still paid it.

    A luxd that went away between the query and the round trip used to cost the
    board as well as the push: the failure propagated before the board could be
    stored, so the next click paid the whole multi-second query again — the one
    cost this cache exists to prevent.
    """
    unreachable = RecordingClient(unreachable=True)
    cache = NoBoard().refreshed(_work(Source(BeadsRows.of([ISSUE])), unreachable))

    assert isinstance(cache, HeldBoard)

    # And what it holds is the board that was built, ready to be the next
    # click's answer rather than a placeholder.
    client = RecordingClient(frame_is_up=False)
    cache.answer(_work(Source(BeadsRows.of([ISSUE])), client))
    assert _rows(client.tables[0]) == ["lux-1"]


def test_a_push_that_never_landed_says_so_rather_than_vanishing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Holding the board is not the same as pretending the user saw it."""
    client = RecordingClient(unreachable=True)

    with caplog.at_level(logging.WARNING):
        NoBoard().refreshed(_work(Source(BeadsRows.of([ISSUE])), client))

    assert "not shown" in caplog.text
    assert "luxd is not running" in caplog.text


def test_a_refresh_that_fails_keeps_the_board_already_held() -> None:
    """A board a few minutes old beats a red message where the board was."""
    journal = Journal()
    client = RecordingClient(journal=journal, frame_is_up=False)
    source = ThenFails(BeadsRows.of([ISSUE]), journal)
    load = BoardLoad(BeadsBoard.for_project("lux"), source)

    held = HeldBoard(load.fresh())  # the prefetch's board
    cache = held.refreshed(_work(source, client))  # the load that fails behind it

    assert cache is held
    assert client.scenes == []  # nothing red replaced it
    assert client.tables == []  # and nothing was pushed at all


def test_a_click_holding_a_board_answers_with_that_board() -> None:
    """The click the whole warm-up is for: the answer is a board, not a word."""
    client = RecordingClient(frame_is_up=False)
    load = BoardLoad(BeadsBoard.for_project("lux"), Source(BeadsRows.of([ISSUE])))

    HeldBoard(load.fresh()).answer(_work(Source(), client))

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

    HeldBoard(load.fresh()).answer(_work(Source(), client))

    assert _rows(client.tables[0]) == ["lux-1"]


def test_a_click_holding_nothing_opens_with_the_placeholder() -> None:
    """The cold click: there is no board yet, so the window says what it is doing."""
    client = RecordingClient(frame_is_up=False)

    NoBoard().answer(_work(Source(BeadsRows.of([ISSUE])), client))

    assert client.tables == []
    assert "Loading issues" in str(client.scenes[0].elements)


def test_a_click_holding_nothing_leaves_a_frame_that_is_up_alone() -> None:
    """Whatever is in a frame already up is older than nothing at all.

    Holding no board, this state has nothing to put in that frame, and the word
    "Loading" over a board somebody is reading is a loss rather than an answer.
    """
    client = RecordingClient(frame_is_up=True)

    NoBoard().answer(_work(Source(BeadsRows.of([ISSUE])), client))

    assert client.scenes == []
    assert client.tables == []
