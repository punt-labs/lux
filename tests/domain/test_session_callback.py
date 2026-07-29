"""SessionCallback validation and CallbackInvocation leaf-id round-trip.

A callback carries a non-empty id and label and refuses an id that would break
the composite leaf id. The invocation renders the leaf id a session's callback
gets and parses a clicked leaf id back into the same session-and-callback, so a
click reaches exactly the session that registered it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ConnectionId


def test_a_callback_carries_a_non_empty_id_and_label() -> None:
    callback = SessionCallback(id="beads", label="Beads")
    assert (callback.id, callback.label) == ("beads", "Beads")


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


def test_the_leaf_id_round_trips_through_the_invocation() -> None:
    invocation = CallbackInvocation(ConnectionId("vox-session"), "beads")
    parsed = CallbackInvocation.from_menu_id(invocation.menu_id)
    assert parsed == invocation


def test_a_leaf_id_without_the_separator_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a callback leaf id"):
        CallbackInvocation.from_menu_id("beads")


def test_a_leaf_id_with_an_empty_callback_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a callback leaf id"):
        CallbackInvocation.from_menu_id("vox-session\x1f")


def test_a_leaf_id_with_an_empty_connection_is_rejected() -> None:
    # A separator-leading id would yield ConnectionId("") — a nonexistent session.
    with pytest.raises(ValueError, match="not a callback leaf id"):
        CallbackInvocation.from_menu_id("\x1fbeads")
