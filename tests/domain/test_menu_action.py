"""MenuAction — the clickable leaf owns both halves of its wire round-trip.

The action serializes itself (``to_wire``) and decodes itself (``from_wire``,
reading ``frame_id`` — the gap-(a) byproduct), stamps its own leaf id for
dispatch, and rejects an agent id carrying the leaf separator at the boundary.
The family is the structural :class:`WireMenuEntry` Protocol.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.menu_action import MenuAction
from punt_lux.domain.hub.menu_models import Menu, MenuSeparator, WireMenuEntry
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.domain.id_separator import ID_SEPARATOR
from punt_lux.domain.ids import ConnectionId


def test_round_trips_without_a_frame_id() -> None:
    action = MenuAction(id="run", label="Run", shortcut="F5")
    assert MenuAction.from_wire(action.to_wire(), loc="m") == action


def test_round_trips_with_a_frame_id() -> None:
    # gap (a): from_wire reads frame_id, so a frame-bound agent item survives.
    action = MenuAction(id="open", label="Open", frame_id="dash")
    restored = MenuAction.from_wire(action.to_wire(), loc="m")
    assert restored == action
    assert restored.frame_id == "dash"


def test_from_wire_rejects_an_id_carrying_the_leaf_separator() -> None:
    bad = {"id": f"a{ID_SEPARATOR}b", "label": "Run"}
    with pytest.raises(ValueError, match="separator"):
        MenuAction.from_wire(bad, loc="m")


def test_from_wire_rejects_a_non_string_frame_id() -> None:
    with pytest.raises(ValueError, match="frame_id"):
        MenuAction.from_wire({"id": "run", "label": "Run", "frame_id": 7}, loc="m")


def test_stamped_for_owner_composes_both_the_leaf_id_and_the_frame_id() -> None:
    action = MenuAction(id="run", label="Run", frame_id="dash")
    owner = ConnectionId("sess-1")
    stamped = action.stamped_for(owner)
    assert stamped.id == CallbackInvocation(owner, "run").menu_id
    assert stamped.label == "Run"
    # gap (a): the frame_id is owner-composed too, else the display's
    # raise_frame(frame_id) never matches the owner-composed scene key.
    assert stamped.frame_id == ConnectionScopedId.compose(owner, "dash")


def test_stamped_frame_id_matches_the_scene_key_scene_presentation_composes() -> None:
    # The crux: a frame-bound agent item's stamped frame_id must be byte-identical
    # to the key ScenePresentation composes for the same (owner, raw frame_id) —
    # both use ConnectionScopedId.compose — so a click's raise_frame finds the
    # actual shown frame. A raw pass-through (the shipped bug) fails this.
    owner = ConnectionId("917218c0")
    raw = "demo-frame"
    stamped = MenuAction(id="run", label="Run", frame_id=raw).stamped_for(owner)
    scene_key = ConnectionScopedId.compose(owner, raw)
    assert stamped.frame_id == scene_key
    assert stamped.frame_id != raw  # proves it is composed, not passed through


def test_stamped_for_leaves_a_frameless_item_frame_id_none() -> None:
    # gap (b) delivery is unaffected: no frame to raise, frame_id stays None.
    stamped = MenuAction(id="run", label="Run").stamped_for(ConnectionId("sess-1"))
    assert stamped.frame_id is None


def test_every_entry_kind_satisfies_the_wire_menu_entry_protocol() -> None:
    # The family is defined structurally, not by a base class.
    assert isinstance(MenuAction(id="a", label="A"), WireMenuEntry)
    assert isinstance(MenuSeparator(), WireMenuEntry)
    assert isinstance(Menu(label="File", items=[]), WireMenuEntry)


def test_the_family_tag_is_the_class_level_type() -> None:
    assert MenuAction.TYPE == "action"
    assert MenuSeparator.TYPE == "separator"
    assert Menu.TYPE == "menu"
