"""DialDeath -- a record of a death names at least one suspect."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.dial_death import DialDeath
from punt_lux.domain.ids import SceneId


def test_a_death_with_no_suspects_is_refused() -> None:
    with pytest.raises(ValueError, match="no suspects"):
        DialDeath(frozenset(), "pair-1", "display")


def test_the_reason_names_the_display_that_ended_the_dial() -> None:
    death = DialDeath(frozenset({SceneId("s")}), "pair-1", "display")

    assert death.reason == "the display at pair-1 ended the connection"


def test_the_reason_of_an_unresponsive_dial_says_it_stopped_answering() -> None:
    death = DialDeath(frozenset({SceneId("s")}), "pair-1", "unresponsive")

    assert death.reason == "the display at pair-1 stopped answering"
