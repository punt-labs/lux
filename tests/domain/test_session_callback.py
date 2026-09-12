"""SessionCallback validation and CallbackInvocation leaf-id round-trip.

A callback carries a non-empty id and label and refuses an id that would break
the composite leaf id. The invocation renders the leaf id a session's callback
gets and parses a clicked leaf id back into the same session-and-callback, so a
click reaches exactly the session that registered it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.session_callback import (
    CallbackInvocation,
    MenuLeaf,
    SessionCallback,
)
from punt_lux.domain.ids import ConnectionId


def test_a_callback_carries_a_non_empty_id_and_label() -> None:
    callback = SessionCallback(id="beads", label="Beads")
    assert (callback.id, callback.label) == ("beads", "Beads")


def test_a_callback_owns_no_frame_by_default() -> None:
    assert SessionCallback(id="beads", label="Beads").frame_id is None


def test_a_callback_may_name_the_frame_it_owns() -> None:
    callback = SessionCallback(id="beads", label="Beads", frame_id="beads-lux")
    assert callback.frame_id == "beads-lux"


@pytest.mark.parametrize("field", ["id", "label"])
def test_an_empty_field_is_rejected(field: str) -> None:
    values = {"id": "beads", "label": "Beads", field: ""}
    with pytest.raises(ValidationError):
        SessionCallback(**values)


def test_an_id_with_the_separator_is_rejected() -> None:
    # The unit separator joins connection and callback in the leaf id; an id that
    # carried it would split ambiguously at dispatch.
    with pytest.raises(ValidationError):
        SessionCallback(id="be\x1fads", label="Beads")


def test_a_blank_frame_id_is_rejected() -> None:
    # ConnectionScopedId.compose applies this identical rule; registration must
    # fail here rather than deep inside menu composition.
    with pytest.raises(ValidationError):
        SessionCallback(id="beads", label="Beads", frame_id=" ")


def test_a_frame_id_with_the_separator_is_rejected() -> None:
    # frame_id is later composed with the owning connection via
    # ConnectionScopedId.compose, which splits on this same separator.
    with pytest.raises(ValidationError):
        SessionCallback(id="beads", label="Beads", frame_id="beads\x1flux")


def test_the_leaf_id_round_trips_through_the_invocation() -> None:
    invocation = CallbackInvocation(ConnectionId("vox-session"), "beads")
    parsed = CallbackInvocation.from_menu_id(invocation.menu_id)
    assert parsed == invocation


def test_a_leaf_id_without_a_kind_tag_is_rejected() -> None:
    # An untagged, kindless id never named a real stamped leaf.
    with pytest.raises(ValueError, match="not a menu leaf id"):
        MenuLeaf.parse("beads")


def test_a_leaf_id_with_an_empty_local_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a menu leaf id"):
        MenuLeaf.parse("cb\x1fvox-session\x1f")


def test_a_leaf_id_with_an_empty_connection_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a menu leaf id"):
        MenuLeaf.parse("cb\x1f\x1fbeads")


def test_a_leaf_id_with_an_unknown_kind_tag_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a menu leaf id"):
        MenuLeaf.parse("xx\x1fvox-session\x1fbeads")


def test_callback_and_menu_leaves_share_a_body_but_differ_by_kind_tag() -> None:
    # The bug this closes: an applet callback "run" and an agent menu item "run"
    # for the same session share the owner<US>local body but carry DISTINCT wire
    # ids, so dispatch can route them apart.
    owner = ConnectionId("sess-1")
    callback = CallbackInvocation(owner, "run").menu_id
    item = MenuLeaf("menu", owner, "run").wire_id
    assert callback != item
    assert MenuLeaf.parse(callback).kind == "callback"
    assert MenuLeaf.parse(item).kind == "menu"
    assert MenuLeaf.parse(item).local_id == "run"


def test_from_menu_id_refuses_a_menu_kind_leaf() -> None:
    # The callback path must never answer an agent menu item, even one whose local
    # id matches a real callback id.
    item = MenuLeaf("menu", ConnectionId("sess-1"), "run").wire_id
    with pytest.raises(ValueError, match="not a callback leaf id"):
        CallbackInvocation.from_menu_id(item)
