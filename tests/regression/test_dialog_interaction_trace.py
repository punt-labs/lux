"""End-to-end interaction-trace parity gate for the Dialog Confirm click.

This test pins the full causal chain: a wire ``RemoteEventHandlerInvocation``
for the Confirm child of a ``DialogElement`` flows through
``HubInteractionDispatch`` into a typed ``ButtonClicked``, into the catalog
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

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.handlers.publish_sink import PublishSink
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay, UnknownElementError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId, Topic
from punt_lux.domain.update import RemoveElement
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogDecoder
from punt_lux.protocol.messages.observer import ObserverMessage
from punt_lux.protocol.renderers import RaisingRendererFactory
from tests.hub_harness import IsolatedHub

if TYPE_CHECKING:
    import pytest

_SCENE = SceneId("save-confirm-scene")
_PANEL_ID = ElementId("root-panel")
_DIALOG_ID = ElementId("save_confirm")
_OK_BUTTON_ID = ElementId("ok")
_CANCEL_BUTTON_ID = ElementId("cancel")
_TOPIC = Topic("dialog_confirmed")

type PublishCallable = Callable[[str, Mapping[str, object]], None]


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
    sink_callable: PublishCallable,
) -> DialogElement:
    """Decode the dialog wire spec with ``sink_callable`` bound as PublishSink."""
    decoder = JsonDialogDecoder(
        renderer_factory=RaisingRendererFactory(),
        emit=_noop_emit,
        element_cls=DialogElement,
        publish_sink=cast("PublishSink", _PublishSinkAdapter(sink_callable)),
    )
    return decoder.decode(_dialog_wire_spec())


@final
class _ConfirmTrace:
    """One decoded dialog, installed on an isolated Hub and ready to be clicked.

    Owns the whole arrangement the trace needs — the Hub store, the pub-sub Hub
    and its subscribing writer, the panel that parents the dialog — so a test
    reads as build-click-assert and the two parity gates differ only in how the
    dialog was decoded.
    """

    hub: IsolatedHub
    panel: _Panel
    dialog: DialogElement
    received: list[ObserverMessage]
    __slots__ = ("dialog", "hub", "panel", "received")

    def __new__(
        cls,
        monkeypatch: pytest.MonkeyPatch,
        build: Callable[[PublishCallable], DialogElement],
        *,
        agent: str,
    ) -> Self:
        self = super().__new__(cls)
        self.hub = IsolatedHub(monkeypatch)
        connection_id = self.hub.connect(agent)
        pubsub = Hub()
        self.received = []
        pubsub.register_writer(connection_id, self.received.append)
        pubsub.subscribe(connection_id, _TOPIC)

        def _publish_sink(topic: str, payload: Mapping[str, object]) -> None:
            pubsub.publish(connection_id, Topic(topic), payload)

        self.dialog = build(_publish_sink)
        # The panel is the scene root and the dialog its child; installing the
        # root recurses through the Composite Protocol, so the dialog and both
        # of its buttons land in the index and the wire click resolves.
        self.panel = _Panel(
            id=str(_PANEL_ID),
            hub_display=self.hub.display,
            scene_id=_SCENE,
            owner_connection_id=connection_id,
        )
        self.panel.install_children((self.dialog,))
        self.hub.install(connection_id, _SCENE, _as_wire(self.panel))
        return self

    def confirm(self) -> None:
        """Click the dialog's Confirm button through the real Hub dispatch."""
        self.hub.click(_SCENE, _OK_BUTTON_ID)

    def assert_dialog_dropped_from_hub_index(self) -> None:
        """Assert the dialog is no longer resolvable in the Hub store."""
        try:
            self.hub.display.resolve(_SCENE, _DIALOG_ID)
        except UnknownElementError:
            return
        msg = "expected dialog to be dropped from HubDisplay index after dismiss"
        raise AssertionError(msg)

    def assert_one_publish_delivered(self) -> None:
        """Assert exactly one ObserverMessage naming the click reached the writer."""
        assert len(self.received) == 1
        delivered = self.received[0]
        assert delivered.topic == str(_TOPIC)
        assert delivered.payload == {
            "kind": "button_clicked",
            "scene_id": str(_SCENE),
            "element_id": str(_OK_BUTTON_ID),
        }


def test_confirm_click_traces_end_to_end_through_every_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the full causal chain for one Confirm click."""
    trace = _ConfirmTrace(
        monkeypatch, _build_dialog_with_publish_sink, agent="parity-agent"
    )
    dialog = trace.dialog

    # --- Preconditions: model fresh, indexes populated ----------------------
    # Bind property reads to locals so mypy doesn't carry the narrowing
    # forward into the post-click assertions further down. The same
    # idiom defeats narrowing on the children tuple shape.
    pre_confirmed: bool = dialog.confirmed
    pre_removed: bool = dialog.removed
    pre_visible: bool = dialog.visible
    pre_children: tuple[AbcElement, ...] = trace.panel.children
    assert pre_confirmed is False
    assert pre_removed is False
    assert pre_visible is True
    assert len(pre_children) == 1
    assert pre_children[0] is dialog
    assert trace.hub.display.resolve(_SCENE, _DIALOG_ID) is dialog

    # --- The act: a wire RemoteEventHandlerInvocation for the Confirm click ---
    trace.confirm()

    # --- The trace: every downstream effect, asserted in causal order ------

    # 1. The catalog handler ran call_model("confirm") against DialogModel —
    #    the model recorded confirmation.
    assert dialog.model.confirmed is True
    assert dialog.confirmed is True

    # 2. The model's _dismiss callback flipped Element-level _removed via
    #    Element.mark_removed.
    assert dialog.model.visible is False
    assert dialog.visible is False
    assert dialog.removed is True

    # 3. The Observer cascade reached the parent: the panel's children
    #    tuple no longer contains the dialog.
    assert trace.panel.children == ()

    # 4. The HubDisplay index dropped the dialog — the parent's prune routed
    #    RemoveElement back through apply.
    trace.assert_dialog_dropped_from_hub_index()

    # 5. The decorator chain's publish call reached Hub.publish, which
    #    queued one ObserverMessage to the subscribing connection's
    #    writer — the subscriber-side analogue of poll_event returning
    #    the payload. The payload names the click and the button it
    #    landed on, so the subscriber need not infer either.
    trace.assert_one_publish_delivered()

    # 6. The handler mutated the scene, so the Hub marked it for the
    #    replicator to resend — the display never repaints from the click.
    assert trace.hub.dirtied() == [_SCENE]


def _build_dialog_through_module_factory(
    sink_callable: PublishCallable,
) -> DialogElement:
    """Decode the wire spec through ``JsonElementFactory``, the production path."""
    test_factory = JsonElementFactory(
        renderer_factory=RaisingRendererFactory(),
        emit=_noop_emit,
        publish_sink=cast("PublishSink", _PublishSinkAdapter(sink_callable)),
    )
    decoded = test_factory.element_from_dict(dict(_dialog_wire_spec()))
    assert isinstance(decoded, DialogElement)
    return decoded


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
    trace = _ConfirmTrace(
        monkeypatch, _build_dialog_through_module_factory, agent="parity-agent-module"
    )

    trace.confirm()

    assert trace.dialog.confirmed is True
    assert trace.dialog.removed is True
    assert trace.panel.children == ()
    trace.assert_dialog_dropped_from_hub_index()
    trace.assert_one_publish_delivered()
