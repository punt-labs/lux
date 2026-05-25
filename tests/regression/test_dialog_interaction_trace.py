"""End-to-end interaction-trace parity gate for the Dialog Confirm click.

This test pins the full causal chain: a wire ``InteractionMessage``
for the Confirm child of a ``DialogElement`` flows through
``Display.interact`` into a typed ``ButtonClicked``, into the catalog
handler the wire decoder installed, into ``DialogModel.confirm`` which
flips ``_confirmed = True`` and invokes the bound ``on_dismiss``
callback that calls ``Element.mark_removed`` on the owning
``DialogElement``. The Element-level Observer cascade notifies the
parent composite (which prunes its children tuple) AND the HubDisplay
root observer (which drops the dialog from the index). The same
click's decorator chain publishes ``"dialog_confirmed"`` through the
Hub, which fans an ``ObserverMessage`` out to the subscribing
connection's writer.

Every assertion below pins one observable downstream effect. A
failure of any single assertion is a real regression — the test does
not exist to make any of them pass; it exists to make every one of
them visible together.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.display import Display
from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay, UnknownElementError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId, Topic
from punt_lux.domain.update import AddElement, RemoveElement
from punt_lux.protocol import elements as elements_pkg
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements import element_from_dict
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogDecoder
from punt_lux.protocol.messages.interaction import InteractionMessage
from punt_lux.protocol.messages.observer import ObserverMessage
from punt_lux.protocol.renderers import RaisingRendererFactory

if TYPE_CHECKING:
    import pytest

_SCENE = SceneId("save-confirm-scene")
_PANEL_ID = ElementId("root-panel")
_DIALOG_ID = ElementId("save_confirm")
_OK_BUTTON_ID = ElementId("ok")
_CANCEL_BUTTON_ID = ElementId("cancel")
_TOPIC = Topic("dialog_confirmed")


def _noop_emit(_msg: object) -> None:
    """Sentinel emit channel — tests never assert against the renderer-emit."""


def _element_id_of(element: AbcElement) -> str:
    """Return the wire id of an AbcElement that exposes ``.id``.

    The Element ABC does not promise an ``id`` property; concrete kinds
    (DialogElement, ButtonElement, this test's _Panel) do. The cast
    documents the structural assumption made at this call site.
    """
    return cast("str", getattr(element, "id", ""))


def _as_wire(element: AbcElement) -> WireElement:
    """Narrow an AbcElement to its structural wire ``Element`` Protocol.

    Every concrete AbcElement kind used here (DialogElement,
    ButtonElement, _Panel) implements ``id``, ``kind``, ``tooltip``,
    ``to_dict``, and ``from_dict``. The cast is the seam between the
    behavioral ABC tree the Hub-tier observes and the structural
    Protocol the Display-tier indexes.
    """
    return cast("WireElement", element)


class _PublishSinkAdapter:
    """Wire a plain callable into a ``PublishSink``-shaped object."""

    __slots__ = ("_fn",)

    _fn: object

    def __new__(cls, fn: object) -> Self:
        self = super().__new__(cls)
        self._fn = fn
        return self

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        cast("PublishSink", self._fn)(topic, payload)


class _ChildPropertyObserver:
    """Closure-as-class so the observer surface stays typed and inspectable.

    The Element ABC's ``add_observer`` signature is ``Callable[[str],
    None]``; this class implements ``__call__`` so the parent's prune
    binding is the single dispatch site.
    """

    _parent: _Panel
    _child: AbcElement

    def __new__(cls, *, parent: _Panel, child: AbcElement) -> Self:
        self = super().__new__(cls)
        self._parent = parent
        self._child = child
        return self

    def __call__(self, property_name: str) -> None:
        if property_name != "removed":
            return
        self._parent.prune_child(self._child)


class _Panel(AbcElement):
    """Test-local composite that observes its children for self-removal.

    Mirrors the ``PanelElement`` shape: when a child flips ``_removed``,
    the parent prunes it from its own children tuple AND drops it from
    the Hub-side index via ``HubDisplay.apply(RemoveElement(...))``.
    The dual prune keeps the parent's local view and the Hub's
    authoritative index in lockstep.
    """

    _id: str
    _children_tuple: tuple[AbcElement, ...]
    _hub_display: HubDisplay
    _scene_id: SceneId
    _owner_connection_id: ConnectionId

    def __new__(
        cls,
        *,
        id: str,
        hub_display: HubDisplay,
        scene_id: SceneId,
        owner_connection_id: ConnectionId,
    ) -> Self:
        self = super().__new__(
            cls, renderer_factory=RaisingRendererFactory(), emit=_noop_emit
        )
        self._id = id
        self._children_tuple = ()
        self._hub_display = hub_display
        self._scene_id = scene_id
        self._owner_connection_id = owner_connection_id
        return self

    @property
    def id(self) -> str:
        """Return the panel's stable identity within its scene."""
        return self._id

    @property
    def children(self) -> tuple[AbcElement, ...]:
        """Return the panel's child tuple (read-only view)."""
        return self._children_tuple

    def _children(self) -> tuple[AbcElement, ...]:
        return self._children_tuple

    def install_children(self, children: tuple[AbcElement, ...]) -> None:
        """Adopt ``children`` and register the parent-as-observer hook."""
        for child in children:
            child.add_observer(_ChildPropertyObserver(parent=self, child=child))
        self._children_tuple = children

    def prune_child(self, child: AbcElement) -> None:
        """Drop ``child`` locally and from the Hub-side index."""
        self._children_tuple = tuple(c for c in self._children_tuple if c is not child)
        child_id = ElementId(_element_id_of(child))
        self._hub_display.apply(
            self._owner_connection_id,
            RemoveElement(scene_id=self._scene_id, element_id=child_id),
        )


def _dialog_wire_spec() -> Mapping[str, object]:
    """Return the wire JSON the agent would ship for a save-confirm dialog."""
    return {
        "kind": "dialog",
        "id": str(_DIALOG_ID),
        "title": "Save changes?",
        "children": [
            {
                "kind": "button",
                "id": str(_OK_BUTTON_ID),
                "label": "OK",
                "handlers": [
                    {
                        "event": "click",
                        "factory": "call_model",
                        "verb": "confirm",
                        "wrap": [
                            {"decorator": "publish", "topics": [str(_TOPIC)]},
                        ],
                    },
                ],
            },
            {
                "kind": "button",
                "id": str(_CANCEL_BUTTON_ID),
                "label": "Cancel",
                "handlers": [
                    {
                        "event": "click",
                        "factory": "call_model",
                        "verb": "cancel",
                    },
                ],
            },
        ],
    }


def _build_dialog_with_publish_sink(
    sink_callable: object,
) -> DialogElement:
    """Decode the dialog wire spec with ``sink_callable`` bound as PublishSink."""
    decoder = JsonDialogDecoder(
        renderer_factory=RaisingRendererFactory(),
        emit=_noop_emit,
        element_cls=DialogElement,
        publish_sink=cast("PublishSink", _PublishSinkAdapter(sink_callable)),
    )
    return decoder.decode(_dialog_wire_spec())


def test_confirm_click_traces_end_to_end_through_every_tier() -> None:
    """Pin the full causal chain for one Confirm click."""
    # --- Tier setup: Hub + HubDisplay + Display + connection wiring ----------
    hub = Hub()
    hub_display = HubDisplay()
    display = Display()

    client_id = display.connect_client(name="parity-agent")
    connection_id = ConnectionId(str(client_id))
    hub_display.register_client(connection_id)

    received: list[ObserverMessage] = []

    def _writer(message: ObserverMessage) -> None:
        received.append(message)

    hub.register_writer(connection_id, _writer)
    hub.subscribe(connection_id, _TOPIC)

    def _publish_sink(topic: str, payload: Mapping[str, object]) -> None:
        hub.publish(connection_id, Topic(topic), payload)

    dialog = _build_dialog_with_publish_sink(_publish_sink)

    # --- Scene install: panel as root, dialog as a child of the panel ------
    panel = _Panel(
        id=str(_PANEL_ID),
        hub_display=hub_display,
        scene_id=_SCENE,
        owner_connection_id=connection_id,
    )
    panel.install_children((dialog,))

    display.add_scene(_SCENE)
    # The agent installs the panel as the scene root and the dialog as
    # its child. The Display layer tracks element ownership for the
    # ``Display.interact`` gate; child buttons are installed alongside
    # so the wire ``InteractionMessage`` resolves to a known element.
    # AbcElement subclasses satisfy the wire ``Element`` Protocol
    # structurally (id, kind, tooltip, to_dict, from_dict); the cast
    # tells mypy what the runtime check already knows.
    display.apply(
        client_id,
        AddElement(scene_id=_SCENE, element=_as_wire(panel), parent_id=None),
    )
    display.apply(
        client_id,
        AddElement(scene_id=_SCENE, element=_as_wire(dialog), parent_id=_PANEL_ID),
    )
    ok_button = dialog.children[0]
    cancel_button = dialog.children[1]
    display.apply(
        client_id,
        AddElement(scene_id=_SCENE, element=_as_wire(ok_button), parent_id=_DIALOG_ID),
    )
    display.apply(
        client_id,
        AddElement(
            scene_id=_SCENE, element=_as_wire(cancel_button), parent_id=_DIALOG_ID
        ),
    )

    # Hub-side index install: the dialog is the root the HubDisplay
    # observer watches for self-dismissal. When ``mark_removed`` fires,
    # the root-observer's "removed" branch routes a RemoveElement back
    # through ``apply`` and the index drops the entry.
    hub_display.apply(
        connection_id,
        AddElement(scene_id=_SCENE, element=_as_wire(dialog), parent_id=None),
    )

    # --- Preconditions: model fresh, indexes populated ----------------------
    # Bind property reads to locals so mypy doesn't carry the narrowing
    # forward into the post-click assertions further down. The same
    # idiom defeats narrowing on the children tuple shape.
    pre_confirmed: bool = dialog.confirmed
    pre_removed: bool = dialog.removed
    pre_visible: bool = dialog.visible
    pre_children: tuple[AbcElement, ...] = panel.children
    assert pre_confirmed is False
    assert pre_removed is False
    assert pre_visible is True
    assert len(pre_children) == 1
    assert pre_children[0] is dialog
    assert hub_display.resolve(_SCENE, _DIALOG_ID) is dialog

    # --- The act: a wire InteractionMessage for the Confirm click ----------
    click = InteractionMessage(
        element_id=str(_OK_BUTTON_ID),
        action="click",
        scene_id=str(_SCENE),
        value=True,
    )
    event = display.interact(client_id, click)

    # --- The trace: every downstream effect, asserted in causal order ------

    # 1. Display.interact constructed and returned the typed event.
    assert event.scene_id == _SCENE
    assert event.element_id == _OK_BUTTON_ID
    assert event.owner_id == client_id

    # 2. The catalog handler ran call_model("confirm") against DialogModel —
    #    the model recorded confirmation.
    assert dialog.model.confirmed is True
    assert dialog.confirmed is True

    # 3. The model's _dismiss callback flipped Element-level _removed via
    #    Element.mark_removed.
    assert dialog.model.visible is False
    assert dialog.visible is False
    assert dialog.removed is True

    # 4. The Observer cascade reached the parent: the panel's children
    #    tuple no longer contains the dialog.
    assert panel.children == ()

    # 5. The HubDisplay index dropped the dialog — the root observer's
    #    "removed" branch routed RemoveElement through apply.
    _assert_dialog_dropped_from_hub_index(hub_display)

    # 6. The decorator chain's publish call reached Hub.publish, which
    #    queued one ObserverMessage to the subscribing connection's
    #    writer — the subscriber-side analogue of poll_event returning
    #    the payload.
    assert len(received) == 1
    delivered = received[0]
    assert delivered.topic == str(_TOPIC)
    assert delivered.payload == {}


def _assert_dialog_dropped_from_hub_index(hub_display: HubDisplay) -> None:
    """Assert the dialog is no longer resolvable in ``hub_display``."""
    try:
        hub_display.resolve(_SCENE, _DIALOG_ID)
    except UnknownElementError:
        return
    msg = "expected dialog to be dropped from HubDisplay index after dismiss"
    raise AssertionError(msg)


def test_confirm_click_traces_through_module_level_element_from_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sibling parity gate using the module-level ``element_from_dict`` path.

    The earlier test constructs ``JsonDialogDecoder`` directly with a
    test-local publish sink. Production code routes wire dicts through
    ``element_from_dict``, which dispatches via the module-level
    ``_ELEMENT_FACTORY``. This sibling swaps that factory for one wired
    with the test's publish sink, then exercises the full trace so any
    future production-vs-test divergence (renderer factory wiring,
    publish-sink contract, kind dispatch) surfaces here.
    """
    hub = Hub()
    hub_display = HubDisplay()
    display = Display()

    client_id = display.connect_client(name="parity-agent-module")
    connection_id = ConnectionId(str(client_id))
    hub_display.register_client(connection_id)

    received: list[ObserverMessage] = []

    def _writer(message: ObserverMessage) -> None:
        received.append(message)

    hub.register_writer(connection_id, _writer)
    hub.subscribe(connection_id, _TOPIC)

    def _publish_sink(topic: str, payload: Mapping[str, object]) -> None:
        hub.publish(connection_id, Topic(topic), payload)

    test_factory = JsonElementFactory(
        renderer_factory=RaisingRendererFactory(),
        emit=_noop_emit,
        publish_sink=cast("PublishSink", _PublishSinkAdapter(_publish_sink)),
    )
    monkeypatch.setattr(elements_pkg, "_ELEMENT_FACTORY", test_factory)

    decoded = element_from_dict(dict(_dialog_wire_spec()))
    assert isinstance(decoded, DialogElement)
    dialog = decoded

    panel = _Panel(
        id=str(_PANEL_ID),
        hub_display=hub_display,
        scene_id=_SCENE,
        owner_connection_id=connection_id,
    )
    panel.install_children((dialog,))

    display.add_scene(_SCENE)
    display.apply(
        client_id,
        AddElement(scene_id=_SCENE, element=_as_wire(panel), parent_id=None),
    )
    display.apply(
        client_id,
        AddElement(scene_id=_SCENE, element=_as_wire(dialog), parent_id=_PANEL_ID),
    )
    ok_button = dialog.children[0]
    cancel_button = dialog.children[1]
    display.apply(
        client_id,
        AddElement(scene_id=_SCENE, element=_as_wire(ok_button), parent_id=_DIALOG_ID),
    )
    display.apply(
        client_id,
        AddElement(
            scene_id=_SCENE, element=_as_wire(cancel_button), parent_id=_DIALOG_ID
        ),
    )
    hub_display.apply(
        connection_id,
        AddElement(scene_id=_SCENE, element=_as_wire(dialog), parent_id=None),
    )

    click = InteractionMessage(
        element_id=str(_OK_BUTTON_ID),
        action="click",
        scene_id=str(_SCENE),
        value=True,
    )
    event = display.interact(client_id, click)

    assert event.scene_id == _SCENE
    assert event.element_id == _OK_BUTTON_ID
    assert dialog.confirmed is True
    assert dialog.removed is True
    assert panel.children == ()
    _assert_dialog_dropped_from_hub_index(hub_display)
    assert len(received) == 1
    assert received[0].topic == str(_TOPIC)
    assert received[0].payload == {}
