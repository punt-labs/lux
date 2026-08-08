"""HubDisplay single-runtime tests — the store's invariants, end to end.

No ImGui. No socket. No JSON. Real domain objects against the authoritative
Hub store: install, mutate, remove, own, and dispatch. The interaction half
drives ``HubInteractionDispatch`` — the same code a display click reaches —
through ``IsolatedHub``, which stands the module singletons up per test.

Two ways the Hub differs from the display-tier mirror this file used to
exercise, both deliberate and asserted below rather than assumed:

- A refusal raises. ``HubOwnershipError`` for a cross-connection write and the
  element's own ``TypeError``/``AttributeError`` for a bad field patch, instead
  of a returned ``Error`` value.
- An invalid interaction is dropped and logged, not raised back. The display is
  a replica: there is nobody on the far end to hand an exception to.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self

import pytest

from punt_lux.domain.container_interaction import ModalClosed
from punt_lux.domain.hub.hub_display import (
    HubDisplay,
    HubOwnershipError,
    UnknownElementError,
)
from punt_lux.domain.hub.scene_snapshot import SceneSnapshot
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty
from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    ComboElement,
    ModalElement,
    ProgressElement,
)
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from tests.hub_harness import IsolatedHub

if TYPE_CHECKING:
    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.scene_presentation import SceneLayout

_SCENE = SceneId("s1")


@dataclass(frozen=True, slots=True)
class _WireButton:
    """A wire-only (non-ABC) element — the store holds it, no click may fire it."""

    id: str
    label: str
    kind: Literal["button"] = "button"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind, "label": self.label}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]), label=str(d.get("label", "")))


def _store(*connections: str) -> tuple[HubDisplay, tuple[ConnectionId, ...]]:
    """Return a fresh store and the named connections registered as its clients."""
    display = HubDisplay()
    ids = tuple(ConnectionId(name) for name in connections)
    for connection_id in ids:
        display.register_client(connection_id)
    return display, ids


def _install(
    display: HubDisplay,
    owner: ConnectionId,
    element: WireElement,
    *,
    scene_id: SceneId = _SCENE,
) -> None:
    """Install ``element`` as a root of ``scene_id``."""
    display.apply(owner, AddElement(scene_id=scene_id, element=element, parent_id=None))


def _button(display: HubDisplay, element_id: str) -> ButtonElement:
    """Narrow the stored element to the ButtonElement these tests installed."""
    elem = display.resolve(_SCENE, ElementId(element_id))
    assert isinstance(elem, ButtonElement)
    return elem


def _progress(display: HubDisplay, element_id: str) -> ProgressElement:
    """Narrow the stored element to the ProgressElement these tests installed."""
    elem = display.resolve(_SCENE, ElementId(element_id))
    assert isinstance(elem, ProgressElement)
    return elem


# -- topology ---------------------------------------------------------------


def test_registered_connections_are_distinct_clients() -> None:
    display, (alice, bob) = _store("alice", "bob")
    assert alice != bob
    assert display.is_client(alice)
    assert display.is_client(bob)
    assert set(display.client_sessions()) == {alice, bob}


def test_an_unregistered_connection_is_not_a_client() -> None:
    display, _ = _store()
    assert not display.is_client(ConnectionId("ghost"))


def test_a_scene_comes_into_existence_with_its_first_root() -> None:
    """The Hub has no ``add_scene``: installing a root is what creates a scene."""
    display, (alice,) = _store("alice")
    assert display.live_scene_ids() == ()

    _install(display, alice, ButtonElement(id="b1", label="hi"))
    _install(display, alice, ButtonElement(id="b2", label="bye"))

    assert display.live_scene_ids() == (_SCENE,)


# -- AddElement -------------------------------------------------------------


def test_add_element_installs_it_and_records_its_owner() -> None:
    display, (alice,) = _store("alice")
    btn = ButtonElement(id="b1", label="hi")

    _install(display, alice, btn)

    assert display.resolve(_SCENE, ElementId("b1")) is btn
    assert display.owner_of(_SCENE, ElementId("b1")) == alice
    assert display.element_count(_SCENE) == 1


def test_re_adding_an_id_replaces_the_element_under_it() -> None:
    """The latest install defines the id — the Hub has no duplicate-id refusal.

    A re-show replaces the whole scene, so the store's rule for a repeated id
    is last-writer-wins rather than a rejection the agent would have to
    reconcile against state it cannot see.
    """
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    _install(display, alice, ButtonElement(id="b1", label="hello"))

    assert [e.id for e in display.scene_roots(_SCENE)] == ["b1"]
    assert _button(display, "b1").label == "hello"


def test_add_element_reaches_a_scene_that_holds_nothing_yet() -> None:
    display, (alice,) = _store("alice")
    ghost_scene = SceneId("ghost")

    _install(display, alice, ButtonElement(id="b1", label="hi"), scene_id=ghost_scene)

    assert display.resolve(ghost_scene, ElementId("b1")).id == "b1"


# -- RemoveElement ----------------------------------------------------------


def test_remove_element_drops_it_from_the_index() -> None:
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    display.apply(alice, RemoveElement(scene_id=_SCENE, element_id=ElementId("b1")))

    with pytest.raises(UnknownElementError):
        display.resolve(_SCENE, ElementId("b1"))
    assert display.scene_roots(_SCENE) == []


def test_removing_an_unknown_element_is_a_no_op() -> None:
    """Removal is idempotent: a frame close and a TTL may both reach one scene."""
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    display.apply(alice, RemoveElement(scene_id=_SCENE, element_id=ElementId("ghost")))

    assert display.element_count(_SCENE) == 1


# -- SetProperty ------------------------------------------------------------


def test_set_property_patches_the_element_in_place() -> None:
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    display.apply(
        alice,
        SetProperty(
            scene_id=_SCENE, element_id=ElementId("b1"), field="label", value="hello"
        ),
    )

    assert _button(display, "b1").label == "hello"


def test_set_property_with_wrong_type_raises_and_leaves_the_value() -> None:
    """The element's own setter is the type authority (DES-039), and it fails loud."""
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    with pytest.raises(TypeError, match="label must be str"):
        display.apply(
            alice,
            SetProperty(
                scene_id=_SCENE, element_id=ElementId("b1"), field="label", value=42
            ),
        )

    assert _button(display, "b1").label == "hi"


def test_set_property_on_an_undeclared_field_raises() -> None:
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    with pytest.raises(AttributeError):
        display.apply(
            alice,
            SetProperty(
                scene_id=_SCENE,
                element_id=ElementId("b1"),
                field="not_a_field",
                value="x",
            ),
        )


def test_set_property_on_bool_field_accepts_bool() -> None:
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    display.apply(
        alice,
        SetProperty(
            scene_id=_SCENE, element_id=ElementId("b1"), field="disabled", value=True
        ),
    )

    assert _button(display, "b1").disabled is True


def test_set_property_on_float_field_accepts_int() -> None:
    """JSON int literals must satisfy float-annotated fields.

    ``json.loads('{"fraction": 1}')`` yields ``int`` 1, not ``float`` 1.0. The
    wire-boundary ``WireContext.require_number`` coerces both; the element's
    setter must match that semantics or a legitimate integer fraction is
    wrongly refused.
    """
    display, (alice,) = _store("alice")
    _install(display, alice, ProgressElement(id="p1", fraction=0.0))

    display.apply(
        alice,
        SetProperty(
            scene_id=_SCENE, element_id=ElementId("p1"), field="fraction", value=1
        ),
    )

    assert _progress(display, "p1").fraction == 1.0


def test_set_property_on_int_field_refuses_float() -> None:
    """The inverse asymmetry: float values do NOT satisfy an ``int`` annotation.

    ``json.dumps(1.0)`` is ``"1.0"``, distinct from ``json.dumps(1)`` (``"1"``),
    so a float literal arriving for an int-only field is a real type mismatch.
    """
    display, (alice,) = _store("alice")
    combo = ComboElement(id="c1", label="Pick", items=["a", "b"], selected=0)
    _install(display, alice, combo)

    with pytest.raises(TypeError, match="selected must be an int"):
        display.apply(
            alice,
            SetProperty(
                scene_id=_SCENE, element_id=ElementId("c1"), field="selected", value=1.0
            ),
        )

    assert combo.selected == 0


def test_set_property_on_float_field_still_refuses_bool() -> None:
    """``bool`` is a subclass of ``int`` but must not silently coerce to ``float``."""
    display, (alice,) = _store("alice")
    _install(display, alice, ProgressElement(id="p1", fraction=0.0))

    with pytest.raises(TypeError, match="fraction must be a number"):
        display.apply(
            alice,
            SetProperty(
                scene_id=_SCENE,
                element_id=ElementId("p1"),
                field="fraction",
                value=True,
            ),
        )

    assert _progress(display, "p1").fraction == 0.0


# -- Ownership --------------------------------------------------------------


def test_cross_connection_set_property_is_refused() -> None:
    display, (alice, bob) = _store("alice", "bob")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    with pytest.raises(HubOwnershipError) as exc_info:
        display.apply(
            bob,
            SetProperty(
                scene_id=_SCENE, element_id=ElementId("b1"), field="label", value="evil"
            ),
        )

    assert exc_info.value.attempting == bob
    assert exc_info.value.owning == alice
    # State unchanged: the ownership check runs before any mutation (PY-EH-1).
    assert _button(display, "b1").label == "hi"


def test_cross_connection_remove_is_refused() -> None:
    display, (alice, bob) = _store("alice", "bob")
    _install(display, alice, ButtonElement(id="b1", label="hi"))

    with pytest.raises(HubOwnershipError):
        display.apply(bob, RemoveElement(scene_id=_SCENE, element_id=ElementId("b1")))

    assert display.resolve(_SCENE, ElementId("b1")).id == "b1"


def test_an_unregistered_connection_still_owns_what_it_installs() -> None:
    """Installing does not require a prior registration; owning still binds.

    A write registers nobody — a session arrives by its own ``identify`` — so an
    install from an unregistered connection lands and is owned by it, and the
    ownership gate protects it from every other connection just the same.
    """
    display, (alice,) = _store("alice")
    ghost = ConnectionId("ghost")

    _install(display, ghost, ButtonElement(id="b1", label="hi"))

    assert display.owner_of(_SCENE, ElementId("b1")) == ghost
    assert not display.is_client(ghost)
    with pytest.raises(HubOwnershipError):
        display.apply(alice, RemoveElement(scene_id=_SCENE, element_id=ElementId("b1")))


# -- Disconnect -------------------------------------------------------------


def test_dropping_a_connection_leaves_its_elements_installed_and_owned() -> None:
    """A session's UI survives the session — only the client registration goes."""
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))
    _install(display, alice, ButtonElement(id="b2", label="bye"))

    display.drop_connection(alice)

    assert not display.is_client(alice)
    assert display.element_count(_SCENE) == 2
    assert {eid for _scene, eid in display.elements_owned_by(alice)} == {
        ElementId("b1"),
        ElementId("b2"),
    }


def test_dropping_an_unknown_connection_is_a_no_op() -> None:
    display, _ = _store()
    display.drop_connection(ConnectionId("ghost"))
    assert display.client_sessions() == {}


# -- Observer cascade -------------------------------------------------------


def test_a_root_dismissing_itself_leaves_the_index() -> None:
    """The store's own notification path: a root's ``removed`` routes to ``apply``.

    ``SubtreeInstaller`` registers a HubDisplay-owned observer on every scene
    root. Flipping ``_removed`` on the element — what a dialog's dismiss
    callback does — must reach the index without anyone calling ``apply``.
    """
    display, (alice,) = _store("alice")
    modal = ModalElement(id="m1", title="Confirm")
    _install(display, alice, modal)

    modal.mark_removed()

    with pytest.raises(UnknownElementError):
        display.resolve(_SCENE, ElementId("m1"))


def test_a_refused_write_notifies_nothing() -> None:
    """A refused patch leaves the element's observers unfired — no half-write."""
    display, (alice, bob) = _store("alice", "bob")
    button = ButtonElement(id="b1", label="hi")
    _install(display, alice, button)
    observed: list[str] = []
    button.add_observer(observed.append)

    with pytest.raises(HubOwnershipError):
        display.apply(
            bob,
            SetProperty(
                scene_id=_SCENE, element_id=ElementId("b1"), field="label", value="evil"
            ),
        )

    assert observed == []


# -- Snapshot ---------------------------------------------------------------


def test_a_snapshot_is_decoupled_from_later_mutation() -> None:
    """The replicator reads copies: a later patch cannot tear an in-flight send."""
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))
    before = display.reader.snapshot(_SCENE)

    display.apply(
        alice,
        SetProperty(
            scene_id=_SCENE, element_id=ElementId("b1"), field="label", value="hello"
        ),
    )

    assert _SnapshotLabels(before).captured() == ["hi"]
    assert _button(display, "b1").label == "hello"


class _SnapshotLabels:
    """The button labels a ``SceneSnapshot`` copied out, read by pushing it.

    A snapshot only reveals its roots to a ``ScenePusher``; this stands in as
    that pusher and keeps what it was handed, so a test can assert on what the
    replicator would have sent.
    """

    _snapshot: SceneSnapshot
    _labels: list[str]
    __slots__ = ("_labels", "_snapshot")

    def __new__(cls, snapshot: SceneSnapshot) -> Self:
        self = super().__new__(cls)
        self._snapshot = snapshot
        self._labels = []
        return self

    def captured(self) -> list[str]:
        """Push the snapshot into this collector and return the labels it held."""
        self._snapshot.push(self)
        return self._labels

    def show_async(
        self,
        scene_id: str,
        elements: list[WireElement],
        *,
        title: str | None = None,
        layout: SceneLayout = "single",
        frame_id: str,
        frame_title: str | None = None,
        frame_size: tuple[int, int] | None = None,
        frame_flags: dict[str, bool] | None = None,
        frame_layout: Literal["tab", "stack"] | None = None,
    ) -> None:
        """Keep the pushed roots' labels — the ``ScenePusher`` side of a resend."""
        del scene_id, title, layout, frame_id, frame_title
        del frame_size, frame_flags, frame_layout
        for root in elements:
            assert isinstance(root, ButtonElement)
            self._labels.append(root.label)


def test_scene_roots_forgets_a_removed_root() -> None:
    display, (alice,) = _store("alice")
    _install(display, alice, ButtonElement(id="b1", label="hi"))
    _install(display, alice, ButtonElement(id="b2", label="bye"))

    display.apply(alice, RemoveElement(scene_id=_SCENE, element_id=ElementId("b1")))

    assert [e.id for e in display.scene_roots(_SCENE)] == ["b2"]


# -- Interaction dispatch ---------------------------------------------------


def test_a_button_click_fires_button_clicked_carrying_its_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    button = ButtonElement(id="b1", label="OK")
    hub.install(alice, _SCENE, button)
    observed: list[ButtonClicked] = []
    button.add_handler(ButtonClicked, observed.append)

    hub.click(_SCENE, ElementId("b1"))

    assert len(observed) == 1
    event = observed[0]
    assert event.element_id == ElementId("b1")
    assert event.scene_id == _SCENE
    assert str(event.owner_id) == str(alice)
    assert hub.dirtied() == [_SCENE]


def test_a_click_does_not_touch_the_property_observers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A click runs the handler registry, not the state-change cascade.

    The two notification paths are separate: property observers exist for
    store-side mutation (a root dismissing itself), and a click that mutates
    nothing must leave them silent.
    """
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    button = ButtonElement(id="b1", label="OK")
    hub.install(alice, _SCENE, button)
    fired: list[ButtonClicked] = []
    observed: list[str] = []
    button.add_handler(ButtonClicked, fired.append)
    button.add_observer(observed.append)

    hub.click(_SCENE, ElementId("b1"))

    assert len(fired) == 1
    assert observed == []


def test_a_checkbox_toggle_fires_value_changed_on_the_real_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The migrated checkbox dispatches through the same path as the button."""
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    checkbox = CheckboxElement(id="c1", label="Bold", value=False)
    hub.install(alice, _SCENE, checkbox)
    observed: list[ValueChanged] = []
    checkbox.add_handler(ValueChanged, observed.append)

    hub.click(_SCENE, ElementId("c1"), event_kind="value_changed", value=True)

    assert [event.value for event in observed] == [True]
    assert observed[0].element_id == ElementId("c1")


def test_a_modal_close_fires_modal_closed_on_the_real_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Hub asks the modal to build its own event from the wire payload."""
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    modal = ModalElement(id="m1", title="Confirm")
    hub.install(alice, _SCENE, modal)
    observed: list[ModalClosed] = []
    modal.add_handler(ModalClosed, observed.append)

    hub.click(_SCENE, ElementId("m1"), event_kind="modal_closed", value=None)

    assert len(observed) == 1
    assert observed[0].element_id == ElementId("m1")
    assert observed[0].scene_id == _SCENE


def test_a_non_scalar_value_change_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ValueChanged.from_wire`` takes a JSON scalar; a list builds no event.

    The precise per-kind shape (a checkbox's ``bool``) is the element's own
    DES-039 invariant, enforced when its setter applies the patch.
    """
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    checkbox = CheckboxElement(id="c1", label="Bold")
    hub.install(alice, _SCENE, checkbox)
    observed: list[ValueChanged] = []
    checkbox.add_handler(ValueChanged, observed.append)

    hub.click(_SCENE, ElementId("c1"), event_kind="value_changed", value=[1, 2])

    assert observed == []
    assert hub.dirtied() == []


def test_a_click_at_a_missing_element_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    hub.install(alice, _SCENE, ButtonElement(id="b1", label="OK"))

    hub.click(_SCENE, ElementId("ghost"))

    assert hub.dirtied() == []


def test_a_click_at_a_missing_scene_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = IsolatedHub(monkeypatch)
    hub.connect("alice")

    hub.click(SceneId("no-such"), ElementId("b1"))

    assert hub.dirtied() == []


def test_a_click_at_a_wire_only_element_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ABC elements declare interaction specs; a wire dataclass fires nothing."""
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    hub.install(alice, _SCENE, _WireButton(id="b1", label="Legacy"))

    hub.click(_SCENE, ElementId("b1"))

    assert hub.dirtied() == []


def test_an_event_kind_the_element_does_not_fire_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checkbox declares only ``value_changed``; a click matches no spec."""
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    checkbox = CheckboxElement(id="c1", label="Bold")
    hub.install(alice, _SCENE, checkbox)
    observed: list[ValueChanged] = []
    checkbox.add_handler(ValueChanged, observed.append)

    hub.click(_SCENE, ElementId("c1"), event_kind="button_clicked")

    assert observed == []
    assert hub.dirtied() == []


def test_a_kindless_invocation_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """An invocation naming no kind fits no element's spec and is not a click."""
    hub = IsolatedHub(monkeypatch)
    alice = hub.connect("alice")
    button = ButtonElement(id="b1", label="OK")
    hub.install(alice, _SCENE, button)
    observed: list[ButtonClicked] = []
    button.add_handler(ButtonClicked, observed.append)

    hub.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(_SCENE),
            element_id="b1",
            action="b1",
            event_kind=None,
            ts=1.0,
            value=True,
        )
    )

    assert observed == []
    assert hub.dirtied() == []
