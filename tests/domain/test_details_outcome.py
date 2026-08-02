"""What became of a Details click, and what each outcome says for itself.

A frame on screen is its own report; a refusal paints nothing at all, so the log
is the only place it can show. The two are two classes so the dispatch tells the
outcome to report itself instead of asking which one it is.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.details_outcome import DetailsRefused, DetailsShown
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


def test_two_refusals_of_one_connection_are_equal() -> None:
    """The outcome is a value: what it carries is the whole of it."""
    assert DetailsRefused(ConnectionId("c1")) == DetailsRefused(ConnectionId("c1"))
    assert DetailsRefused(ConnectionId("c1")) != DetailsRefused(ConnectionId("c2"))
