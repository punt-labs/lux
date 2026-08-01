"""The Hub end of a board: what each answer means, and where failures stop.

Two contracts, and both are about not losing something expensive to a round trip
that did not land. A raise nobody could answer counts as a yes, because blanking
a board that is plainly up is worse than skipping a placeholder nobody needed. A
push that could not be sent is logged rather than raised, because the board it
carried has already cost a multi-second query and the caller is keeping it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.applets.board_channel import BoardChannel
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsRows

from .board_doubles import ISSUE, Journal, RecordingClient, UnraisableClient

if TYPE_CHECKING:
    import pytest

_BOARD = BeadsBoard.for_project("lux")


def _channel(client: object) -> BoardChannel:
    """A channel over a stand-in client, which is structural rather than typed."""
    return BoardChannel(client)  # type: ignore[arg-type]  # structural stand-in


def test_a_frame_that_is_up_is_reported_as_up() -> None:
    assert _channel(RecordingClient(frame_is_up=True)).raised("beads-lux") is True


def test_a_frame_that_is_not_up_is_reported_as_not_up() -> None:
    assert _channel(RecordingClient(frame_is_up=False)).raised("beads-lux") is False


def test_a_raise_nobody_could_answer_counts_as_up(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The board may well be on screen; blanking it on a failed trip is worse."""
    with caplog.at_level(logging.WARNING):
        answer = _channel(UnraisableClient(Journal())).raised("beads-lux")

    assert answer is True
    assert "could not be raised" in caplog.text


def test_a_board_with_issues_goes_down_the_table_route() -> None:
    """The Hub constructs the board's live chrome, so its data crosses as a table."""
    client = RecordingClient()
    _channel(client).send(_BOARD.request(BeadsRows.of([ISSUE])))

    assert len(client.tables) == 1
    assert client.scenes == []


def test_a_message_goes_down_the_plain_scene_route() -> None:
    client = RecordingClient()
    _channel(client).send(_BOARD.failure("bd: command not found"))

    assert client.tables == []
    assert len(client.scenes) == 1


def test_a_refusal_is_logged_where_it_cannot_be_rendered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The render is what failed, so there is nowhere to show that it did."""
    client = RecordingClient(refuse=True)

    with caplog.at_level(logging.ERROR):
        _channel(client).send(_BOARD.request(BeadsRows.of([ISSUE])))

    assert "not shown" in caplog.text


def test_a_hub_that_could_not_be_reached_ends_here(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raise here would cost its caller the board it just spent seconds loading."""
    with caplog.at_level(logging.WARNING):
        _channel(RecordingClient(unreachable=True)).send(
            _BOARD.request(BeadsRows.of([ISSUE]))
        )

    assert "luxd unreachable" in caplog.text
