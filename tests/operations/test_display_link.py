"""DisplayLinkOperations — the four-way DisplayLinkage classification.

Every case is driven from fakes: no display fixture is required for either the
connected or disconnected/held cases, because ``get_link`` never round-trips
to the display (design display-presence-demand-driven.md §6).
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING, Self, cast

from punt_lux.operations.display_link import DisplayLinkOperations
from punt_lux.operations.models.display_link import (
    ConnectedLinkState,
    DisconnectedLinkState,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import SceneId
    from punt_lux.operations.display_link import ReplicatorLink
    from punt_lux.operations.display_port import DisplayPort


class _FakePort:
    """A ``DisplayPort`` whose ``is_connected`` is a fixed, preset value."""

    is_connected: bool
    __slots__ = ("is_connected",)

    def __new__(cls, *, connected: bool) -> Self:
        self = super().__new__(cls)
        self.is_connected = connected
        return self


class _FakeDisplay:
    """A store whose ``live_scene_ids`` returns a preset count of ids."""

    _scene_ids: tuple[str, ...]
    __slots__ = ("_scene_ids",)

    def __new__(cls, *, scene_count: int) -> Self:
        self = super().__new__(cls)
        self._scene_ids = tuple(f"s{i}" for i in range(scene_count))
        return self

    def live_scene_ids(self) -> tuple[str, ...]:
        return self._scene_ids


class _FakeReplicator:
    """A ``ReplicatorLink`` whose ``disconnected_delay`` is a fixed value."""

    disconnected_delay: float
    __slots__ = ("disconnected_delay",)

    def __new__(cls, *, delay: float = 0.0) -> Self:
        self = super().__new__(cls)
        self.disconnected_delay = delay
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        del scene_id

    def mark_menus(self) -> None:
        pass


def _link(
    *, connected: bool, scene_count: int, delay: float = 0.0
) -> DisplayLinkOperations:
    return DisplayLinkOperations(
        cast("DisplayPort", _FakePort(connected=connected)),
        cast("HubDisplay", _FakeDisplay(scene_count=scene_count)),
        cast("ReplicatorLink", _FakeReplicator(delay=delay)),
    )


def test_connected_with_no_scenes_is_connected_idle() -> None:
    result = _link(connected=True, scene_count=0).get_link()
    assert isinstance(result, ConnectedLinkState)
    assert result.linkage == "connected_idle"


def test_connected_with_live_scenes_is_connected_active() -> None:
    result = _link(connected=True, scene_count=1).get_link()
    assert isinstance(result, ConnectedLinkState)
    assert result.linkage == "connected_active"


def test_disconnected_with_no_scenes_is_disconnected() -> None:
    result = _link(connected=False, scene_count=0, delay=8.0).get_link()
    assert isinstance(result, DisconnectedLinkState)
    assert result.linkage == "disconnected"
    assert result.retry_delay_seconds == 8.0


def test_disconnected_with_held_scenes_is_held() -> None:
    result = _link(connected=False, scene_count=2, delay=32.0).get_link()
    assert isinstance(result, DisconnectedLinkState)
    assert result.linkage == "held"
    assert result.retry_delay_seconds == 32.0


def test_connected_state_carries_no_retry_delay_field_at_all() -> None:
    # Not merely None — the field does not exist on the connected shape
    # (OO Five Rules #5: no discriminated-state field left as an Optional).
    result = _link(connected=True, scene_count=0).get_link()
    assert not hasattr(result, "retry_delay_seconds")


# -- multi-host introspection: hub_host / hub_pid / live_scene_count (§9) ---


def test_connected_carries_live_scene_count_and_host_identity() -> None:
    result = _link(connected=True, scene_count=3).get_link()
    assert isinstance(result, ConnectedLinkState)
    assert result.live_scene_count == 3
    assert result.hub_host == socket.gethostname()
    assert result.hub_pid == os.getpid()


def test_disconnected_carries_live_scene_count_and_host_identity() -> None:
    result = _link(connected=False, scene_count=5, delay=4.0).get_link()
    assert isinstance(result, DisconnectedLinkState)
    assert result.live_scene_count == 5
    assert result.hub_host == socket.gethostname()
    assert result.hub_pid == os.getpid()
