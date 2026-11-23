"""ListenerSlot — the connection's listener and its callbacks as one indivisible pair.

The slot is where the design's central rule is made structural rather than
remembered: a callback exists only while the listener that registered it holds the
slot. Every test here is that rule from one side — taking the slot clears what the
last occupant owned, releasing it clears both at once, ownership is decided by
object identity so no recurring token can impersonate an occupant, and the
constructor refuses the one combination the rule forbids.
"""

from __future__ import annotations

from typing import final

import pytest

from punt_lux.domain.hub.listener_slot import ListenerSlot
from punt_lux.domain.hub.session_callback import SessionCallback


@final
class _Leg:
    """A listen leg stand-in; two instances are two different occupants."""

    def wake(self) -> None:
        """Delivery is elsewhere: this class exists to have an identity."""


def _beads() -> SessionCallback:
    return SessionCallback(id="beads", label="Beads")


def test_an_empty_slot_holds_nothing() -> None:
    slot = ListenerSlot()
    assert slot.is_held is False
    assert slot.listener is None
    assert slot.callbacks == ()


def test_the_occupant_is_recognised_by_identity_not_by_kind() -> None:
    """A token that can recur would let a superseded session pass as its successor.

    The connection id is shared by every session of one identity, and a bare "I
    installed something" flag is shared by all of them too. Only the object that
    installed itself is unique to the incarnation that installed it.
    """
    first, second = _Leg(), _Leg()
    slot = ListenerSlot().occupied_by(first)
    assert slot.held_by(first) is True
    assert slot.held_by(second) is False


def test_taking_the_slot_leaves_the_previous_occupants_callbacks_behind() -> None:
    """A new occupant starts empty: the entries suited only the last one."""
    slot = ListenerSlot().occupied_by(_Leg()).with_callback(_beads())
    assert slot.callbacks == (_beads(),)

    successor = _Leg()
    taken = slot.occupied_by(successor)

    assert taken.held_by(successor)
    assert taken.callbacks == ()


def test_releasing_the_slot_cannot_leave_the_callbacks_behind() -> None:
    """The pair is why no reader can see a callback whose listener has gone.

    Clicks route and registrations commit on other threads, so a state with the
    listener cleared and the callbacks still present is one they can read. Holding
    both in one value means there is no such state to reach.
    """
    released = ListenerSlot().occupied_by(_Leg()).with_callback(_beads()).released()

    assert released.is_held is False
    assert released.listener is None
    assert released.callbacks == ()


def test_a_callback_is_found_by_its_id() -> None:
    slot = ListenerSlot().occupied_by(_Leg()).with_callback(_beads())
    assert slot.owns("beads") is True
    assert slot.owns("something-else") is False


def test_registering_a_known_id_replaces_rather_than_duplicates() -> None:
    slot = (
        ListenerSlot()
        .occupied_by(_Leg())
        .with_callback(SessionCallback(id="beads", label="Beads"))
        .with_callback(SessionCallback(id="beads", label="Beads Browser"))
    )
    assert slot.callbacks == (SessionCallback(id="beads", label="Beads Browser"),)


def test_adding_a_callback_leaves_the_occupant_alone() -> None:
    leg = _Leg()
    slot = ListenerSlot().occupied_by(leg).with_callback(_beads())
    assert slot.held_by(leg)


def test_an_unheld_slot_refuses_a_callback() -> None:
    """The gates that keep this from happening are the registry's, not the type's.

    Every caller compares against the occupant before it registers, so this call
    is not one the running system makes. The type still refuses it, because a rule
    the module states is a rule the module should be unable to break.
    """
    with pytest.raises(ValueError, match="callback needs its listener"):
        ListenerSlot().with_callback(_beads())


def test_the_constructor_refuses_a_callback_with_no_listener() -> None:
    """The refusal is at the root, so no path to the pair can open later.

    ``with_callback`` is one way to ask for it; a new transition that forgot the
    rule would be another. Guarding the constructor answers all of them at once.
    """
    with pytest.raises(ValueError, match="callback needs its listener"):
        ListenerSlot(None, {"beads": _beads()})
