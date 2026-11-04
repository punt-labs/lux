"""A display that has gone mute is declared dead by the real keepalive loop.

The keepalive's own bytes and the lock it takes are not evidence that the display is
alive: a ping the display never answers must end in the dial recorded unresponsive and
dropped, however recently something was written to it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

import pytest

from punt_lux.domain.hub import dial_socket, socket_line
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.liveness import DisplayLiveness
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from tests.domain.display_double import Display
from tests.link_access import generation_of, writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.display_requests import DisplayRequests

_WINDOW = 0.2


@final
class _LinkClients:
    """The keepalive's clients, over one real link: it asks and drops, nothing more."""

    _link: DisplayLink
    dropped: list[DialRef]
    __slots__ = ("_link", "dropped")

    def __new__(cls, link: DisplayLink) -> Self:
        self = super().__new__(cls)
        self._link = link
        self.dropped = []
        return self

    def asks(self) -> DisplayRequests:
        return self._link.desk.asks()

    def drop_unresponsive(self, dial: DialRef) -> None:
        self.dropped.append(dial)
        self._link.drop_if_current(dial, cause="unresponsive")


@pytest.fixture
def display() -> Iterator[Display]:
    shown = Display()
    yield shown
    shown.close()


@pytest.fixture(autouse=True)
def short_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket_line, "SCENE_WRITE_DEADLINE_SECONDS", _WINDOW)
    monkeypatch.setattr(dial_socket, "SEND_TIMEOUT_CEILING_SECONDS", _WINDOW + 0.5)


@pytest.mark.parametrize("before", ["nothing", "a_completed_write"])
def test_a_mute_display_is_recorded_unresponsive_and_its_dial_dropped(
    display: Display, before: str
) -> None:
    link = DisplayLink(display, recv_timeout=3.0)
    link.connect()
    generation = generation_of(link)
    clients = _LinkClients(link)
    time.sleep(_WINDOW + 0.1)  # nothing has moved for D: only the ping can speak
    if before == "a_completed_write":
        writer_of(link).send_scene(ScenePresentation(frame_id="a").message("a", []))

    DisplayLiveness(clients, ping_timeout=0.05).check_once()

    assert generation.ended == "unresponsive"
    assert clients.dropped == [generation.ref]
    assert not link.is_connected
