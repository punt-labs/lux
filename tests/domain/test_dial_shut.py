"""Shutting a dial releases its socket and records no end: a Hub end records nothing."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.domain.display_double import Display
from tests.link_access import bare_connection

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.display_connection import DisplayConnection


@pytest.fixture
def connection() -> Iterator[DisplayConnection]:
    display = Display()
    made = bare_connection(display, 1.0)
    made.open()
    yield made
    made.close()
    display.close()


def test_a_dial_that_is_shut_has_no_recorded_end(
    connection: DisplayConnection,
) -> None:
    generation = connection.require()

    generation.shut()

    assert generation.ended is None
