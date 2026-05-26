"""Element ABC handler registry + Observer surface.

The dispatch surface lives on the Element ABC:

- ``add_handler(event_type, handler)`` / ``remove_handler(event_type, handler)``
  register and deregister per-type callbacks.
- ``fire(event)`` invokes every handler registered for ``type(event)``
  against a snapshot of the handler list so mutations during dispatch
  cannot affect the in-flight call.

The Observer surface — ``add_observer``, ``removed``, ``mark_removed`` —
is the single channel parent composites use to react to a child element
being removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from punt_lux.domain.element_abc import Element
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol import RemoteEventHandlerInvocation
from punt_lux.protocol.elements.button import ButtonElement
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

    @property
    def id(self) -> str:
        return "leaf"


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
    elem.mark_removed()
    after = elem.removed
    assert before is False
    assert after is True


def test_mark_removed_notifies_observers() -> None:
    elem = _Leaf()
    notifications: list[str] = []
    elem.add_observer(notifications.append)
    elem.mark_removed()
    assert notifications == ["removed"]


def test_mark_removed_is_idempotent() -> None:
    elem = _Leaf()
    notifications: list[str] = []
    elem.add_observer(notifications.append)
    elem.mark_removed()
    elem.mark_removed()
    assert notifications == ["removed"]


def test_observer_added_after_mark_removed_is_not_notified_on_repeat() -> None:
    elem = _Leaf()
    elem.mark_removed()
    late: list[str] = []
    elem.add_observer(late.append)
    elem.mark_removed()  # idempotent — no fresh notification fires
    assert late == []


def test_mark_removed_isolates_per_observer_exceptions() -> None:
    elem = _Leaf()
    after: list[str] = []

    def boom(_change: str) -> None:
        raise RuntimeError("subscriber blew up")

    elem.add_observer(boom)
    elem.add_observer(after.append)
    elem.mark_removed()
    assert elem.removed is True
    assert after == ["removed"]


def test_remote_dispatch_group_rejects_empty_handlers() -> None:
    """``RemoteDispatchGroup`` requires at least one handler."""
    import pytest

    from punt_lux.domain.handlers.remote_dispatch import RemoteDispatchGroup

    with pytest.raises(ValueError, match="at least one handler"):
        RemoteDispatchGroup(
            handlers=(),
            send=lambda _msg: None,
            element_id="btn",
            action="click",
        )


def test_wrap_handlers_for_remote_groups_button_click_handlers() -> None:
    button = ButtonElement(id="confirm", label="Confirm")
    local_runs: list[str] = []
    sent: list[RemoteEventHandlerInvocation] = []

    def _first(_event: ButtonClicked) -> None:
        local_runs.append("first")

    def _second(_event: ButtonClicked) -> None:
        local_runs.append("second")

    button.add_handler(ButtonClicked, _first)
    button.add_handler(ButtonClicked, _second)

    button.wrap_handlers_for_remote(sent.append)

    assert button.handler_count(ButtonClicked) == 2
    assert button.handler_summary() == {"ButtonClicked": 2}

    button.fire(
        ButtonClicked(
            scene_id=SceneId("dialog"),
            element_id=ElementId("confirm"),
            owner_id=ClientId("display"),
        )
    )

    assert local_runs == []
    assert len(sent) == 1
    assert sent[0].element_id == "confirm"
    assert sent[0].action == "confirm"
    assert sent[0].value is True


def test_wrap_handlers_for_remote_recurses_into_composite_children() -> None:
    """Child buttons inside a composite get wrapped; the parent does not."""
    from punt_lux.protocol.elements.dialog import DialogElement

    dialog = DialogElement(id="dlg", title="Confirm")
    child_button = ButtonElement(id="child-btn", label="OK")
    child_button.add_handler(ButtonClicked, lambda _e: None)
    dialog.install_children((child_button,))

    sent: list[RemoteEventHandlerInvocation] = []
    dialog.wrap_handlers_for_remote(sent.append)

    assert child_button.handler_count(ButtonClicked) == 1
    child_button.fire(
        ButtonClicked(
            scene_id=SceneId("s"),
            element_id=ElementId("child-btn"),
            owner_id=ClientId("display"),
        )
    )
    assert len(sent) == 1
    assert sent[0].element_id == "child-btn"


def test_wrap_handlers_for_remote_is_noop_for_non_button() -> None:
    """Calling ``wrap_handlers_for_remote`` on a non-button leaf is a no-op."""
    leaf = _Leaf()
    leaf.add_handler(_Click, lambda _e: None)
    sent: list[RemoteEventHandlerInvocation] = []
    leaf.wrap_handlers_for_remote(sent.append)
    seen: list[_Click] = []
    leaf.add_handler(_Click, seen.append)
    leaf.fire(_Click(button="left"))
    assert len(sent) == 0
    assert len(seen) == 1


def test_wrap_handlers_for_remote_is_idempotent_for_button_bucket() -> None:
    button = ButtonElement(id="confirm", label="Confirm")
    sent: list[RemoteEventHandlerInvocation] = []
    button.add_handler(ButtonClicked, lambda _event: None)
    button.add_handler(ButtonClicked, lambda _event: None)

    button.wrap_handlers_for_remote(sent.append)
    button.wrap_handlers_for_remote(sent.append)

    button.fire(
        ButtonClicked(
            scene_id=SceneId("dialog"),
            element_id=ElementId("confirm"),
            owner_id=ClientId("display"),
        )
    )

    assert button.handler_count(ButtonClicked) == 2
    assert len(sent) == 1
