"""What became of a Details click, and what each outcome says for itself.

A frame on screen is its own report; the two outcomes that paint nothing have
the log as the only place they can show, and they show different things — one
knows the Hub holds no session, the other only that nothing was bound to ask.
They are three classes so the dispatch tells the outcome to report itself
instead of asking which one it is, and so one click can never leave two lines.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.details_outcome import (
    DetailsRefused,
    DetailsShown,
    DetailsUnbound,
)
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    import pytest


def test_a_refusal_names_the_connection_the_click_came_from(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        DetailsRefused(ConnectionId("voxd")).reported()

    assert "voxd" in caplog.text
    assert "no longer holds a session for" in caplog.text


def test_a_shown_frame_reports_nothing_because_it_is_on_the_screen(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        DetailsShown().reported()

    assert caplog.text == ""


def test_an_unbound_click_says_nothing_was_bound_and_nothing_about_the_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two reasons a click paints nothing; only the one that was checked is said."""
    with caplog.at_level(logging.DEBUG):
        DetailsUnbound(ConnectionId("c1")).reported()

    assert len(caplog.records) == 1
    assert "before luxd bound its renderer" in caplog.text
    assert "no longer holds a session for" not in caplog.text


def test_each_outcome_that_paints_nothing_leaves_exactly_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = ConnectionId("c1")

    with caplog.at_level(logging.DEBUG):
        DetailsRefused(conn).reported()
        DetailsUnbound(conn).reported()

    assert len(caplog.records) == 2  # one apiece, never two for one click


def test_two_refusals_of_one_connection_are_equal() -> None:
    """The outcome is a value: what it carries is the whole of it."""
    assert DetailsRefused(ConnectionId("c1")) == DetailsRefused(ConnectionId("c1"))
    assert DetailsRefused(ConnectionId("c1")) != DetailsRefused(ConnectionId("c2"))
