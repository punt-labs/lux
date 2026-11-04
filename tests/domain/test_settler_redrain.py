"""A settler drains a second time only when a display end was recorded under its drain.

The first drain reads what the socket held. A display or unresponsive end recorded
after that drain began (a failed write, the keepalive giving up) means the drain may
have missed what the display sent before it died, so the settler looks once more. It
does not look again when the drain itself found the stream's end, when the end was
recorded before the drain began, or when the Hub's own request is all there is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.dial_drain import DialDrain
from tests.domain.display_double import Display
from tests.link_access import bare_connection, drop_route, reading_of

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection


@pytest.fixture
def connection() -> Iterator[DisplayConnection]:
    display = Display()
    made = bare_connection(display, 1.0)
    made.open()
    yield made
    made.close()
    display.close()


def _drains_made(
    connection: DisplayConnection,
    monkeypatch: pytest.MonkeyPatch,
    *,
    during_first: Callable[[DialGeneration], None],
    saw_end: bool,
) -> int:
    """Settle the connection's dial and count the drains the settler made."""
    runs: list[int] = []

    def counted(self: DialDrain, generation: DialGeneration) -> bool:
        runs.append(1)
        if len(runs) == 1:
            during_first(generation)
        return saw_end

    monkeypatch.setattr(DialDrain, "run", counted)
    hold = reading_of(connection).claim_for_listener(drop_route, drop_route)
    assert hold is not None
    hold.settler.settle()
    return len(runs)


def _nothing(_generation: DialGeneration) -> None:
    return


def _display_end(generation: DialGeneration) -> None:
    generation.end("display")


def _unresponsive_end(generation: DialGeneration) -> None:
    generation.end("unresponsive")


class TestTheSecondDrain:
    @pytest.mark.parametrize("record", [_display_end, _unresponsive_end])
    def test_it_is_made_when_an_end_is_recorded_while_the_first_drain_ran(
        self,
        connection: DisplayConnection,
        monkeypatch: pytest.MonkeyPatch,
        record: Callable[[DialGeneration], None],
    ) -> None:
        connection.require().request_hub()  # asked to end; nothing recorded yet

        assert (
            _drains_made(connection, monkeypatch, during_first=record, saw_end=False)
            == 2
        )

    def test_it_is_not_made_when_the_first_drain_found_the_end_itself(
        self, connection: DisplayConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection.require().request_hub()

        assert (
            _drains_made(connection, monkeypatch, during_first=_nothing, saw_end=True)
            == 1
        )

    def test_it_is_not_made_when_the_end_was_recorded_before_the_drain_began(
        self, connection: DisplayConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection.require().end("display")

        assert (
            _drains_made(connection, monkeypatch, during_first=_nothing, saw_end=False)
            == 1
        )

    def test_it_is_not_made_when_only_the_hub_asked_for_the_end(
        self, connection: DisplayConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection.require().request_hub()

        assert (
            _drains_made(connection, monkeypatch, during_first=_nothing, saw_end=False)
            == 1
        )
