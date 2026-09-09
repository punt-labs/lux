"""SceneOperationsDeps -- the four-field bundle SceneOperations.__new__ takes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.operations.scene_deps import SceneOperationsDeps


class _Recorder:
    """A minimal ``DirtyMarker`` stand-in -- construction only, never called."""

    def mark_dirty(self, scene_id: object) -> None:
        del scene_id

    def mark_menus(self) -> None:
        pass


def _deps() -> SceneOperationsDeps:
    return SceneOperationsDeps(HubDisplay(), _Recorder(), hub_element_factory, Hub())


def test_every_field_round_trips() -> None:
    display, replicator, hub = HubDisplay(), _Recorder(), Hub()
    deps = SceneOperationsDeps(display, replicator, hub_element_factory, hub)
    assert deps.display is display
    assert deps.replicator is replicator
    assert deps.element_factory is hub_element_factory
    assert deps.hub is hub


def test_is_frozen() -> None:
    deps = _deps()
    with pytest.raises(FrozenInstanceError):
        deps.hub = Hub()  # type: ignore[misc]  # proving frozen=True raises
