"""HubDisplay.apply(AddElement) recurses into composite children.

Regression for the bug where ``apply`` installed only the root and left
composite children unindexed. A click on a buried child Button would
then fail ``resolve`` and the interaction silently dropped.

The Composite Protocol (``children`` property returning a tuple) is the
gate — any wire element exposing it must have every descendant landed
in the index by a single ``apply(AddElement(...))`` call.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

import pytest

from punt_lux.domain.hub.hub_display import HubDisplay, UnknownElementError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement

_SCENE = SceneId("composite-scene")
_CONN = ConnectionId("composite-conn")
_ROOT_ID = ElementId("root")
_CHILD_A_ID = ElementId("child-a")
_CHILD_B_ID = ElementId("child-b")
_GRANDCHILD_ID = ElementId("grandchild")


@dataclass(frozen=True, slots=True)
class _Leaf:
    """Wire-shaped leaf element — no children property."""

    id: str
    kind: Literal["leaf"] = "leaf"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]))


@dataclass(frozen=True, slots=True)
class _Composite:
    """Wire-shaped composite — satisfies the Composite Protocol."""

    id: str
    children: tuple[_Leaf | _Composite, ...] = ()
    kind: Literal["composite"] = "composite"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]))


def test_apply_add_element_installs_every_composite_descendant() -> None:
    """Every descendant of a composite root lands in the index."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    root = _Composite(
        id=str(_ROOT_ID),
        children=(
            _Leaf(id=str(_CHILD_A_ID)),
            _Composite(
                id=str(_CHILD_B_ID),
                children=(_Leaf(id=str(_GRANDCHILD_ID)),),
            ),
        ),
    )

    hub_display.apply(
        _CONN,
        AddElement(scene_id=_SCENE, element=root, parent_id=None),
    )

    assert hub_display.resolve(_SCENE, _ROOT_ID) is root
    assert hub_display.resolve(_SCENE, _CHILD_A_ID).id == str(_CHILD_A_ID)
    assert hub_display.resolve(_SCENE, _CHILD_B_ID).id == str(_CHILD_B_ID)
    assert hub_display.resolve(_SCENE, _GRANDCHILD_ID).id == str(_GRANDCHILD_ID)


def test_remove_element_walks_subtree_recorded_by_install_recursion() -> None:
    """RemoveElement at the root drops every descendant installed by recursion."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    inner = _Composite(
        id=str(_CHILD_B_ID),
        children=(_Leaf(id=str(_GRANDCHILD_ID)),),
    )
    root = _Composite(id=str(_ROOT_ID), children=(inner,))

    hub_display.apply(_CONN, AddElement(scene_id=_SCENE, element=root, parent_id=None))
    hub_display.apply(_CONN, RemoveElement(scene_id=_SCENE, element_id=_ROOT_ID))

    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, _GRANDCHILD_ID)
