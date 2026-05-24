"""Element ABC handler registry + Observer surface.

The dispatch surface lives on the Element ABC:

- ``add_handler(event_type, handler)`` / ``remove_handler(event_type, handler)``
  register and deregister per-type callbacks.
- ``fire(event)`` invokes every handler registered for ``type(event)``
  against a snapshot of the handler list so mutations during dispatch
  cannot affect the in-flight call.

The Observer surface — ``add_observer``, ``removed``, ``_mark_removed`` —
is the single channel parent composites use to react to a child element
being removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.renderers import RaisingRendererFactory


@dataclass(frozen=True, slots=True)
class _Click:
    """Concrete Event used by tests."""

    button: str


@dataclass(frozen=True, slots=True)
class _Change:
    """Distinct Event type so per-type bucketing is observable."""

    value: int


def _emit(_evt: object) -> None:
    return


class _Leaf(Element):
    """Concrete leaf element — Element ABC requires a subclass.

    Uses the RaisingRendererFactory because dispatch tests never call
    render(); any accidental render would surface as a loud RuntimeError.
    """

    def __new__(cls) -> Self:
        return super().__new__(
            cls, renderer_factory=RaisingRendererFactory(), emit=_emit
        )


def test_fire_dispatches_to_registered_handler_for_its_type() -> None:
    elem = _Leaf()
    seen: list[_Click] = []
    elem.add_handler(_Click, seen.append)
    elem.fire(_Click(button="left"))
    assert seen == [_Click(button="left")]


def test_fire_ignores_handlers_registered_for_other_event_types() -> None:
    elem = _Leaf()
    seen_clicks: list[_Click] = []
    seen_changes: list[_Change] = []
    elem.add_handler(_Click, seen_clicks.append)
    elem.add_handler(_Change, seen_changes.append)
    elem.fire(_Change(value=7))
    assert seen_clicks == []
    assert seen_changes == [_Change(value=7)]


def test_fire_dispatches_in_registration_order() -> None:
    elem = _Leaf()
    order: list[str] = []
    elem.add_handler(_Click, lambda _e: order.append("first"))
    elem.add_handler(_Click, lambda _e: order.append("second"))
    elem.add_handler(_Click, lambda _e: order.append("third"))
    elem.fire(_Click(button="left"))
    assert order == ["first", "second", "third"]


def test_remove_handler_drops_subsequent_dispatches() -> None:
    elem = _Leaf()
    seen: list[_Click] = []
    handler = seen.append
    elem.add_handler(_Click, handler)
    elem.remove_handler(_Click, handler)
    elem.fire(_Click(button="left"))
    assert seen == []


def test_remove_handler_is_a_noop_for_unregistered_handler() -> None:
    elem = _Leaf()
    elem.remove_handler(_Click, lambda _e: None)
    elem.fire(_Click(button="left"))  # must not raise


def test_handler_mutating_registry_during_fire_does_not_affect_in_flight_call() -> None:
    elem = _Leaf()
    seen: list[str] = []

    def first(_e: _Click) -> None:
        seen.append("first")
        elem.add_handler(_Click, lambda _e: seen.append("added-during-fire"))

    def second(_e: _Click) -> None:
        seen.append("second")

    elem.add_handler(_Click, first)
    elem.add_handler(_Click, second)
    elem.fire(_Click(button="left"))
    assert seen == ["first", "second"]


def test_mark_removed_flips_removed_from_false_to_true() -> None:
    elem = _Leaf()
    before = elem.removed
    elem._mark_removed()
    after = elem.removed
    assert before is False
    assert after is True


def test_mark_removed_notifies_observers() -> None:
    elem = _Leaf()
    notifications: list[str] = []
    elem.add_observer(notifications.append)
    elem._mark_removed()
    assert notifications == ["removed"]


def test_mark_removed_is_idempotent() -> None:
    elem = _Leaf()
    notifications: list[str] = []
    elem.add_observer(notifications.append)
    elem._mark_removed()
    elem._mark_removed()
    assert notifications == ["removed"]


def test_observer_added_after_mark_removed_is_not_notified_on_repeat() -> None:
    elem = _Leaf()
    elem._mark_removed()
    late: list[str] = []
    elem.add_observer(late.append)
    elem._mark_removed()  # idempotent — no fresh notification fires
    assert late == []
