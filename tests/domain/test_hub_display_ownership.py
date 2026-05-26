"""HubDisplay.apply enforces ownership on SetProperty and RemoveElement.

Without the check, any connection could mutate or evict any other
connection's elements from the Hub mirror. Display-side ``Display.apply``
already gates on ownership; the Hub mirror must enforce the same rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

import pytest

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty

_SCENE = SceneId("ownership-scene")
_OWNER = ConnectionId("owner-conn")
_STRANGER = ConnectionId("stranger-conn")
_ELEMENT_ID = ElementId("element")


@dataclass(frozen=True, slots=True)
class _WireLeaf:
    """Wire-shaped leaf — satisfies the Element Protocol structurally."""

    id: str
    kind: Literal["leaf"] = "leaf"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]))


def _seed_owner_element() -> HubDisplay:
    """Install one element owned by ``_OWNER`` and return the populated display."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    hub_display.register_client(_STRANGER)
    hub_display.apply(
        _OWNER,
        AddElement(
            scene_id=_SCENE,
            element=_WireLeaf(id=str(_ELEMENT_ID)),
            parent_id=None,
        ),
    )
    return hub_display


def test_remove_element_rejects_non_owner() -> None:
    """A stranger cannot RemoveElement against an element they do not own."""
    hub_display = _seed_owner_element()

    with pytest.raises(HubOwnershipError):
        hub_display.apply(
            _STRANGER,
            RemoveElement(scene_id=_SCENE, element_id=_ELEMENT_ID),
        )
    # The owner's element survives the rejected removal.
    assert hub_display.owner_of(_SCENE, _ELEMENT_ID) == _OWNER


def test_set_property_rejects_non_owner() -> None:
    """A stranger cannot SetProperty against an element they do not own.

    The ownership check fires before the frozen-wire ``TypeError`` would,
    so the stranger sees ``HubOwnershipError``, not a misleading
    "frozen element" message.
    """
    hub_display = _seed_owner_element()

    with pytest.raises(HubOwnershipError):
        hub_display.apply(
            _STRANGER,
            SetProperty(
                scene_id=_SCENE,
                element_id=_ELEMENT_ID,
                field="label",
                value="hijacked",
            ),
        )


def test_owner_can_still_remove_their_own_element() -> None:
    """The check rejects strangers, not the legitimate owner."""
    hub_display = _seed_owner_element()

    hub_display.apply(
        _OWNER,
        RemoveElement(scene_id=_SCENE, element_id=_ELEMENT_ID),
    )


# -- replace_scene ---------------------------------------------------------


def test_replace_scene_installs_fresh_roots() -> None:
    """``replace_scene`` with no prior scene installs all roots."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)

    leaf_a = _WireLeaf(id="a")
    leaf_b = _WireLeaf(id="b")
    hub_display.replace_scene(_OWNER, _SCENE, [leaf_a, leaf_b])

    assert hub_display.owner_of(_SCENE, ElementId("a")) == _OWNER
    assert hub_display.owner_of(_SCENE, ElementId("b")) == _OWNER
    roots = hub_display.scene_roots(_SCENE)
    root_ids = {e.id for e in roots}
    assert root_ids == {"a", "b"}


def test_replace_scene_removes_old_roots_and_installs_new() -> None:
    """``replace_scene`` replaces the existing scene — old roots are gone."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)

    old = _WireLeaf(id="old")
    hub_display.replace_scene(_OWNER, _SCENE, [old])
    assert hub_display.owner_of(_SCENE, ElementId("old")) == _OWNER

    new = _WireLeaf(id="new")
    hub_display.replace_scene(_OWNER, _SCENE, [new])

    roots = hub_display.scene_roots(_SCENE)
    root_ids = {e.id for e in roots}
    assert root_ids == {"new"}

    from punt_lux.domain.hub.element_index import UnknownElementError

    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, ElementId("old"))
