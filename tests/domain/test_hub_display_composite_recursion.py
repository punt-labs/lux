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
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty
from punt_lux.protocol.elements import (
    ButtonElement,
    CollapsingHeaderElement,
    Tab,
    TabBarElement,
    TextElement,
)

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


# -- scene_roots returns only roots (re-push must not hoist children) --------


def _install_tab_bar_scene() -> HubDisplay:
    """Install an ABC tab_bar (tabs → text children) as the sole scene root."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    bar = TabBarElement(
        id="tb",
        tabs=(
            Tab(
                tab_id="tab-1",
                label="One",
                children=(TextElement(id="t1", content="a"),),
            ),
            Tab(
                tab_id="tab-2",
                label="Two",
                children=(TextElement(id="t2", content="b"),),
            ),
        ),
        active_tab="tab-1",
    )
    hub_display.apply(_CONN, AddElement(scene_id=_SCENE, element=bar, parent_id=None))
    return hub_display


def test_scene_roots_excludes_composite_children() -> None:
    """A composite's children never appear as scene roots.

    ``scene_roots`` drives the interaction re-push; if it returned children
    alongside the root, each child would be hoisted to a top-level sibling
    and duplicated against its in-tree copy.
    """
    hub_display = _install_tab_bar_scene()

    roots = hub_display.scene_roots(_SCENE)

    assert [r.id for r in roots] == ["tb"]


def test_tab_change_repush_keeps_single_root_no_duplication() -> None:
    """A tab switch (SetProperty + re-push) leaves exactly the original root.

    Reproduces the live-window bug: an interaction re-push on an ABC tabbed
    container flattened the tree, hoisting every tab's children to top-level
    roots and duplicating them. The re-pushed root set must equal the initial
    root set.
    """
    hub_display = _install_tab_bar_scene()
    initial_roots = [r.id for r in hub_display.scene_roots(_SCENE)]

    hub_display.apply(
        _CONN,
        SetProperty(
            scene_id=_SCENE,
            element_id=ElementId("tb"),
            field="active_tab",
            value="tab-2",
        ),
    )
    repushed_roots = [r.id for r in hub_display.scene_roots(_SCENE)]

    assert repushed_roots == initial_roots == ["tb"]
    # The child text elements stay reachable as children, never promoted.
    assert hub_display.resolve(_SCENE, ElementId("t1")).id == "t1"
    assert hub_display.resolve(_SCENE, ElementId("t2")).id == "t2"


def test_header_toggle_repush_keeps_single_root_no_duplication() -> None:
    """A collapsing_header toggle re-push leaves exactly the original root."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    header = CollapsingHeaderElement(
        id="ch",
        label="Section",
        open=False,
        children=(
            TextElement(id="t1", content="a"),
            ButtonElement(id="b1", label="go"),
        ),
    )
    hub_display.apply(
        _CONN, AddElement(scene_id=_SCENE, element=header, parent_id=None)
    )
    initial_roots = [r.id for r in hub_display.scene_roots(_SCENE)]

    hub_display.apply(
        _CONN,
        SetProperty(
            scene_id=_SCENE,
            element_id=ElementId("ch"),
            field="open",
            value=True,
        ),
    )
    repushed_roots = [r.id for r in hub_display.scene_roots(_SCENE)]

    assert repushed_roots == initial_roots == ["ch"]
    assert hub_display.resolve(_SCENE, ElementId("t1")).id == "t1"
    assert hub_display.resolve(_SCENE, ElementId("b1")).id == "b1"
