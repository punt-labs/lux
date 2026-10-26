"""The manifest is declared only on a dial this call itself made."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.request_desk import RequestDesk
from punt_lux.domain.ids import SceneId
from tests.domain.display_double import Display

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from punt_lux.domain.hub.dial_generation import DialGeneration


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


def _declarations(monkeypatch: pytest.MonkeyPatch) -> list[Sequence[str]]:
    """Record every manifest the desk is asked to declare, writing none."""
    declared: list[Sequence[str]] = []

    def record(_desk: RequestDesk, scene_ids: Sequence[str]) -> None:
        declared.append(scene_ids)

    monkeypatch.setattr(RequestDesk, "declare", record)
    return declared


class TestTheDialThatDeclares:
    def test_a_fresh_dial_declares_what_the_hub_holds(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        declared = _declarations(monkeypatch)
        link = DisplayLink(display, recv_timeout=3.0)

        scene_ids = link.open_as_hub(lambda: [SceneId("a")])

        assert scene_ids == (SceneId("a"),)
        assert declared == [(SceneId("a"),)]
        link.close()

    def test_a_link_already_open_declares_nothing(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        declared = _declarations(monkeypatch)
        link = DisplayLink(display, recv_timeout=3.0)
        link.connect(listen=True)

        assert link.open_as_hub(lambda: [SceneId("a")]) == ()
        assert declared == []
        link.close()

    def test_a_dial_another_caller_made_in_the_gap_is_not_declared_on(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        declared = _declarations(monkeypatch)
        link = DisplayLink(display, recv_timeout=3.0)
        real = DisplayConnection.open_listening

        def lost_the_race(connection: DisplayConnection) -> DialGeneration | None:
            connection.open()  # another caller dials first
            return real(connection)

        monkeypatch.setattr(DisplayConnection, "open_listening", lost_the_race)

        scene_ids = link.open_as_hub(lambda: [SceneId("a")])

        assert scene_ids == ()
        assert declared == []
        link.close()
