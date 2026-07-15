"""Anonymous (empty-id) elements never collide in the Hub store.

The id-uniqueness contract exempts anonymous elements: a bare separator
carries the empty-string sentinel and may repeat freely within a scene.
The Hub store must honour that — several anonymous elements in one scene
each need a distinct slot, or the later one silently overwrites the earlier
in the per-scene store and in root tracking, dropping separators from a
re-push.

These tests pin the invariant end to end: two separators installed as roots
both survive ``scene_roots`` (the interaction re-push source) and a re-show,
while named-element lookup and removal are untouched.
"""

from __future__ import annotations

from typing import cast

import pytest

from punt_lux.domain.element import Element
from punt_lux.domain.hub.deferral_errors import NestedLegacyWriteError
from punt_lux.domain.hub.element_index import ElementIndex
from punt_lux.domain.hub.hub_display import HubDisplay, UnknownElementError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement
from punt_lux.protocol.elements import (
    InputNumberElement,
    SeparatorElement,
    TextElement,
)
from punt_lux.protocol.elements.layout import LegacyGroupElement

_SCENE = SceneId("anon-scene")
_CONN = ConnectionId("anon-conn")


# -- ElementIndex unit: anonymous roots get distinct keys -------------------


def test_two_anonymous_roots_get_distinct_keys() -> None:
    """Installing two anonymous roots yields two distinct store keys."""
    index = ElementIndex()
    sep_a = SeparatorElement()
    sep_b = SeparatorElement()

    key_a = index.install_root(_SCENE, ElementId(sep_a.id), sep_a)
    key_b = index.install_root(_SCENE, ElementId(sep_b.id), sep_b)

    assert key_a != key_b
    assert index.scene_roots(_SCENE) == [sep_a, sep_b]


def test_named_root_key_is_its_own_id() -> None:
    """A named root keys on its own id — unchanged by the anonymous path."""
    index = ElementIndex()
    text = TextElement(id="a", content="one")

    key = index.install_root(_SCENE, ElementId("a"), text)

    assert key == ElementId("a")
    assert index.lookup(_SCENE, ElementId("a")) is text


def test_anonymous_children_get_distinct_keys() -> None:
    """Two anonymous children under one parent never overwrite each other."""
    index = ElementIndex()
    parent = TextElement(id="p", content="parent")
    index.install_root(_SCENE, ElementId("p"), parent)
    sep_a = SeparatorElement()
    sep_b = SeparatorElement()

    key_a = index.install_child(_SCENE, ElementId("p"), sep_a)
    key_b = index.install_child(_SCENE, ElementId("p"), sep_b)

    assert key_a != key_b
    assert index.lookup(_SCENE, key_a) is sep_a
    assert index.lookup(_SCENE, key_b) is sep_b


# -- HubDisplay: separators survive install, re-push, and re-show -----------


def _show(hub: HubDisplay, *roots: SeparatorElement | TextElement) -> None:
    """Replace the scene with ``roots`` through the authoritative Hub path."""
    hub.replace_scene(_CONN, _SCENE, roots)


def test_multiple_separators_survive_install() -> None:
    """Two separators around a named element all land as ordered roots."""
    hub = HubDisplay()
    sep_top = SeparatorElement()
    text = TextElement(id="a", content="one")
    sep_bottom = SeparatorElement()

    _show(hub, sep_top, text, sep_bottom)

    assert hub.scene_roots(_SCENE) == [sep_top, text, sep_bottom]


def test_both_separators_survive_a_re_push() -> None:
    """The re-push source (``scene_roots``) keeps both separators every read.

    ``scene_roots`` is what the interaction re-push resends; reading it twice
    must return both separators, not a single merged one.
    """
    hub = HubDisplay()
    sep_top = SeparatorElement()
    sep_bottom = SeparatorElement()

    _show(hub, sep_top, TextElement(id="a", content="one"), sep_bottom)

    first = hub.scene_roots(_SCENE)
    second = hub.scene_roots(_SCENE)
    separators = [r for r in first if isinstance(r, SeparatorElement)]
    assert len(separators) == 2
    assert first == second


def test_re_show_does_not_accumulate_separators() -> None:
    """Re-showing the same scene replaces separators rather than piling them up.

    Anonymous roots are owner-tracked under their synthesized handles, so the
    re-show's owned-root cleanup clears the prior separators before installing
    the new ones — the root count stays flat across repeated shows.
    """
    hub = HubDisplay()

    _show(hub, SeparatorElement(), TextElement(id="a", content="1"), SeparatorElement())
    _show(hub, SeparatorElement(), TextElement(id="a", content="2"), SeparatorElement())

    roots = hub.scene_roots(_SCENE)
    separators = [r for r in roots if isinstance(r, SeparatorElement)]
    assert len(roots) == 3
    assert len(separators) == 2


def test_named_lookup_and_removal_unaffected_by_anonymous_repeats() -> None:
    """Removing the named element leaves both separators intact."""
    hub = HubDisplay()
    sep_top = SeparatorElement()
    sep_bottom = SeparatorElement()
    _show(hub, sep_top, TextElement(id="a", content="one"), sep_bottom)

    assert hub.resolve(_SCENE, ElementId("a")).id == "a"

    hub.apply(_CONN, RemoveElement(scene_id=_SCENE, element_id=ElementId("a")))

    with pytest.raises(UnknownElementError):
        hub.resolve(_SCENE, ElementId("a"))
    assert hub.scene_roots(_SCENE) == [sep_top, sep_bottom]


# -- anonymous composite root resolves its buried legacy child --------------


def test_write_to_legacy_child_of_anonymous_group_names_the_group() -> None:
    """A patch to a buried legacy child under an anonymous group defers cleanly.

    The child's edges live under the group's synthesized store handle, not under
    its empty wire id. Resolving the enclosing root by store handle names the
    group so the write defers to ``show``; resolving by wire id would find no
    descendants and misreport the store as inconsistent — a ``ValueError`` where
    the client deserves a ``NestedLegacyWriteError`` naming the container.
    """
    hub = HubDisplay()
    hub.register_client(_CONN)
    group = LegacyGroupElement(
        id="",  # anonymous root — stored under a synthesized handle
        children=[InputNumberElement(id="buried", label="s")],
    )
    # The production scene decoder yields legacy elements as ``Element``; the cast
    # mirrors that runtime contract past a codec-signature variance quibble.
    hub.apply(
        _CONN,
        AddElement(scene_id=_SCENE, element=cast("Element", group), parent_id=None),
    )

    with pytest.raises(NestedLegacyWriteError) as exc_info:
        hub.write_seam.field_realization(_SCENE, ElementId("buried"), {"value": 5.0})

    assert exc_info.value.root_kind == "group"
