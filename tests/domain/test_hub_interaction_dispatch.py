"""Direct tests for the Display→Hub interaction dispatch seam."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, final
from unittest.mock import MagicMock

from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_interaction_dispatch import HubInteractionDispatch
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    import pytest


def test_hub_interaction_dispatch_runs_grouped_button_handlers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("confirm")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    button = ButtonElement(id=str(element_id), label="Confirm")
    seen: list[tuple[str, str]] = []

    def _first(event: ButtonClicked) -> None:
        seen.append(("first", str(event.owner_id)))

    def _second(event: ButtonClicked) -> None:
        seen.append(("second", str(event.owner_id)))

    button.add_handler(ButtonClicked, _first)
    button.add_handler(ButtonClicked, _second)
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    mock_replicator = MagicMock()

    import punt_lux.domain.hub as hub_module

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", mock_replicator
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="confirm",
            event_kind="button_clicked",
            ts=1.0,
            value=True,
        )
    )

    assert seen == [
        ("first", str(owner)),
        ("second", str(owner)),
    ]
    # A click marks the scene dirty; the replicator resends it, not the dispatch.
    mock_replicator.mark_dirty.assert_called_once_with(scene_id)


def test_an_owner_literally_named_unowned_is_distinct_from_a_genuinely_unowned_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ConnectionId that spells "unowned" must not collide with the sentinel.

    The attribution sentinel for a genuinely unowned element (a departure
    released it) has to be a string no real ConnectionId can equal --
    otherwise a session literally named "unowned" would be indistinguishable
    from "no owner at all".
    """
    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    mischievous_owner = ConnectionId("unowned")  # a real, live owner named that
    departed_owner = ConnectionId("departed")
    isolated_display.register_client(mischievous_owner)
    isolated_display.register_client(departed_owner)

    live_owned = ButtonElement(id="live-owned", label="Owned")
    genuinely_unowned = ButtonElement(id="unowned-elem", label="Unowned")
    seen: dict[str, str] = {}
    live_owned.add_handler(
        ButtonClicked, lambda e: seen.__setitem__("live", str(e.owner_id))
    )
    genuinely_unowned.add_handler(
        ButtonClicked, lambda e: seen.__setitem__("genuine", str(e.owner_id))
    )
    isolated_display.apply(
        mischievous_owner,
        AddElement(scene_id=scene_id, element=live_owned, parent_id=None),
    )
    isolated_display.apply(
        departed_owner,
        AddElement(scene_id=scene_id, element=genuinely_unowned, parent_id=None),
    )
    isolated_display.drop_connection(departed_owner)  # releases it; content stays

    import punt_lux.domain.hub as hub_module

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", MagicMock()
    )

    for element_id in ("live-owned", "unowned-elem"):
        HubInteractionDispatch.dispatch(
            RemoteEventHandlerInvocation(
                scene_id=str(scene_id),
                element_id=element_id,
                action="confirm",
                event_kind="button_clicked",
                ts=1.0,
                value=True,
            )
        )

    assert seen["live"] == "unowned"  # the real owner's own name, verbatim
    assert seen["genuine"] == "__unowned__"  # the sentinel, not a real name
    assert seen["live"] != seen["genuine"]


def _isolated_router(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[HubClientRegistry, CallbackRouter, MagicMock]:
    """Swap the process router/replicator for fresh ones; return the three."""
    registry = HubClientRegistry()
    router = CallbackRouter(registry)
    replicator = MagicMock()
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_callback_router", router
    )
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", replicator
    )
    return registry, router, replicator


@final
class _SilentLeg:
    """A listen leg stand-in — a session must hold one to own a menu callback."""

    def wake(self) -> None:
        """The push is not what this test drives; the routing is."""


def test_menu_click_routes_the_callback_to_its_owning_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A callback-leaf menu click is held for the session that registered it."""
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback

    registry, router, replicator = _isolated_router(monkeypatch)
    conn = ConnectionId("vox-1")
    leg = _SilentLeg()
    registry.attach_listener(conn, ClientIdentity(kind="app", name="voxd"), leg)
    registry.register_callback(conn, SessionCallback(id="music", label="Music"), leg)

    menu_id = CallbackInvocation(conn, "music").menu_id
    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None, element_id=menu_id, action="menu", ts=1.0, value=None
        )
    )

    held = router.pending(conn)
    assert [inv.callback_id for inv in held] == ["music"]
    replicator.mark_menus.assert_not_called()


def test_menu_click_for_a_departed_session_repushes_the_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A callback click for a session that never registered re-pushes, no crash."""
    from punt_lux.domain.hub.session_callback import CallbackInvocation

    _registry, _router, replicator = _isolated_router(monkeypatch)
    menu_id = CallbackInvocation(ConnectionId("gone"), "music").menu_id
    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None, element_id=menu_id, action="menu", ts=1.0, value=None
        )
    )
    replicator.mark_menus.assert_called_once_with()


def test_a_details_click_is_answered_by_the_hub_not_routed_to_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Details command is the Hub's own: it runs here, and nothing is held."""
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.details_binding import DetailsBinding
    from punt_lux.domain.hub.details_outcome import DetailsShown
    from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback

    registry, router, replicator = _isolated_router(monkeypatch)
    conn = ConnectionId("vox-1")
    leg = _SilentLeg()
    registry.attach_listener(conn, ClientIdentity(kind="app", name="voxd"), leg)
    registry.register_callback(conn, SessionCallback(id="music", label="Music"), leg)
    renderer = MagicMock()
    renderer.render_details.return_value = DetailsShown()
    binding = DetailsBinding()
    binding.bind(renderer)
    monkeypatch.setattr(
        "punt_lux.domain.hub.details_instance.hub_client_details", binding
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None,
            element_id=CallbackInvocation.details(conn).menu_id,
            action="menu",
            ts=1.0,
            value=None,
        )
    )

    renderer.render_details.assert_called_once_with(conn)
    assert router.pending(conn) == ()  # nothing was held for the client
    replicator.mark_menus.assert_not_called()


def test_a_details_click_for_a_client_that_never_registered_still_reaches_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Hub owns the command, so it answers whether or not the client is there."""
    from punt_lux.domain.hub.details_binding import DetailsBinding
    from punt_lux.domain.hub.details_outcome import DetailsRefused
    from punt_lux.domain.hub.session_callback import CallbackInvocation

    _registry, _router, replicator = _isolated_router(monkeypatch)
    conn = ConnectionId("gone")
    renderer = MagicMock()
    renderer.render_details.return_value = DetailsRefused(conn)  # not there
    binding = DetailsBinding()
    binding.bind(renderer)
    monkeypatch.setattr(
        "punt_lux.domain.hub.details_instance.hub_client_details", binding
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None,
            element_id=CallbackInvocation.details(conn).menu_id,
            action="menu",
            ts=1.0,
            value=None,
        )
    )

    # The operation decides there is nothing to show; the dispatch does not
    # second-guess it, and never re-pushes the menu for a Hub-owned command.
    renderer.render_details.assert_called_once_with(conn)
    replicator.mark_menus.assert_not_called()


def test_menu_click_for_a_malformed_leaf_id_is_rejected_without_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leaf id without the owner separator is malformed: rejected, no crash.

    Every real leaf a click can carry is now stamped ``owner<US>item_id`` by the
    registry (agent bar) or by ``CallbackInvocation`` (Clients menu), so a bare id
    never names a real leaf. It is not the agent-item drop path any more — that
    path is gone — it is an ``invalid_request`` guard: logged, no delivery, no
    re-push (there is no real leaf to re-push for).
    """
    _registry, _router, replicator = _isolated_router(monkeypatch)
    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None, element_id="app-beads", action="menu", ts=1.0, value=None
        )
    )
    replicator.mark_menus.assert_not_called()


def test_frameless_agent_menu_click_is_delivered_to_the_owning_inbox_session() -> None:
    """Gap (b): a frameless agent ``menu_set`` click reaches the owning MCP session.

    An agent that called ``menu_set`` holds an inbox (armed by ``ensure_writer``),
    not a listen leg. Its menu leaf is a ``menu``-kind :class:`MenuLeaf`, so the
    click parses to that kind and is delivered as a reserved ``lux.menu`` business
    event on that session's inbox — the event ``recv()`` drains, with no prior
    ``topic_subscribe``. On ``main`` the click was dropped in the non-callback
    branch; this is the regression that fails there and passes here.
    """
    from punt_lux.domain.hub.hub_display import hub_display
    from punt_lux.domain.hub.inbox import drain_inbox, ensure_writer
    from punt_lux.domain.hub.session_callback import MenuLeaf

    conn = ConnectionId("agent-menu-inbox-1")
    ensure_writer(conn)  # arms the inbox + registers the client as a live session
    try:
        leaf_id = MenuLeaf("menu", conn, "run_btn").wire_id
        HubInteractionDispatch.dispatch(
            RemoteEventHandlerInvocation(
                scene_id=None,
                element_id=leaf_id,
                action="menu",
                ts=1.0,
                value={"menu": "Tools", "item": "Run"},
            )
        )
        delivered = drain_inbox(conn)
        assert [(m.topic, dict(m.payload)) for m in delivered] == [
            ("lux.menu", {"menu": "Tools", "item": "run_btn"}),
        ]
    finally:
        hub_display.drop_connection(conn)


def test_a_departed_agent_menu_click_is_not_delivered_and_repushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frameless agent click for a session gone from the live set is not delivered.

    The delivery gate reuses the router's live read, so a departed owner is
    ``provider_gone``: nothing lands on any inbox and the menu re-pushes — the
    agent-path counterpart to the callback-path departed test above.
    """
    from punt_lux.domain.hub.inbox import drain_inbox
    from punt_lux.domain.hub.session_callback import MenuLeaf

    _registry, _router, replicator = _isolated_router(monkeypatch)
    conn = ConnectionId("agent-departed")  # never registered → not live
    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None,
            element_id=MenuLeaf("menu", conn, "run_btn").wire_id,
            action="menu",
            ts=1.0,
            value={"menu": "Tools", "item": "Run"},
        )
    )
    assert drain_inbox(conn) == ()  # nothing delivered to a departed session
    replicator.mark_menus.assert_called_once_with()  # the click re-pushes the menu


def test_a_same_named_callback_and_menu_item_route_apart() -> None:
    """One session owning BOTH a callback "run" and a menu item "run" routes each
    by the leaf's KIND, not by whether a callback exists.

    The callback-kind leaf lands on the callback hold; the menu-kind leaf lands on
    the inbox as ``lux.menu`` carrying the raw item id. On ``main`` both leaves are
    the same ``owner<US>run`` id, so the menu click is misrouted to the callback
    and never reaches the inbox — the regression this proves.
    """
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.hub_display import hub_display
    from punt_lux.domain.hub.inbox import drain_inbox, ensure_writer
    from punt_lux.domain.hub.replicator_instance import hub_callback_router
    from punt_lux.domain.hub.session_callback import (
        CallbackInvocation,
        MenuLeaf,
        SessionCallback,
    )

    conn = ConnectionId("dual-owner")
    leg = _SilentLeg()
    clients = hub_display.clients
    clients.attach_listener(conn, ClientIdentity(kind="app", name="dual"), leg)
    clients.register_callback(conn, SessionCallback(id="run", label="Run"), leg)
    ensure_writer(conn)  # arm the inbox; the same session owns a menu item too
    try:
        HubInteractionDispatch.dispatch(
            RemoteEventHandlerInvocation(
                scene_id=None,
                element_id=CallbackInvocation(conn, "run").menu_id,
                action="menu",
                ts=1.0,
                value=None,
            )
        )
        HubInteractionDispatch.dispatch(
            RemoteEventHandlerInvocation(
                scene_id=None,
                element_id=MenuLeaf("menu", conn, "run").wire_id,
                action="menu",
                ts=1.0,
                value={"menu": "Tools", "item": "Run"},
            )
        )
        held = [inv.callback_id for inv in hub_callback_router.pending(conn)]
        delivered = [(m.topic, dict(m.payload)) for m in drain_inbox(conn)]
        assert held == ["run"]  # only the callback leaf reached the hold
        assert delivered == [("lux.menu", {"menu": "Tools", "item": "run"})]
    finally:
        hub_display.drop_connection(conn)


def test_agent_menu_set_click_round_trips_from_set_to_recv() -> None:
    """The full agent loop: menu_set → click → recv, through the operations facade.

    An identified session sets a bar; the registry stamps its leaf id; a click on
    that stamped id is delivered to the session's inbox; ``receive`` returns the
    reserved ``lux.menu`` event carrying the agent's own item id.
    """
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.hub_display import hub_display
    from punt_lux.domain.hub.replicator_instance import hub_menu_registry
    from punt_lux.operations import Scope, SetMenuRequest
    from punt_lux.tools.tools import OPERATIONS

    conn = ConnectionId("surface-loop-1")
    scope = Scope(conn)
    hub_display.identify_client(conn, ClientIdentity(kind="mcp-session", name="agent"))
    try:
        OPERATIONS.set_menu(
            SetMenuRequest.parse(
                [{"label": "Tools", "items": [{"label": "Run", "id": "run_btn"}]}]
            ),
            scope=scope,
        )
        leaf = hub_menu_registry.wire_snapshot()[0]["items"]
        assert isinstance(leaf, list)
        leaf_id = leaf[0]["id"]
        assert isinstance(leaf_id, str)

        HubInteractionDispatch.dispatch(
            RemoteEventHandlerInvocation(
                scene_id=None,
                element_id=leaf_id,
                action="menu",
                ts=1.0,
                value={"menu": "Tools", "item": "Run"},
            )
        )

        received = OPERATIONS.receive(scope=scope)
        assert received.event is not None
        assert received.event.topic == "lux.menu"
        assert received.event.payload == {"menu": "Tools", "item": "run_btn"}
    finally:
        hub_display.drop_connection(conn)
        hub_menu_registry.drop_session(conn)


def test_hub_interaction_dispatch_missing_scene_id_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``scene_id`` is None the dispatch logs a warning and returns."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=None,
            element_id="btn",
            action="click",
            ts=1.0,
            value=True,
        )
    )


def test_hub_interaction_dispatch_unknown_element_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the element is not in the Hub index the dispatch returns."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id="scene",
            element_id="missing",
            action="click",
            ts=1.0,
            value=True,
        )
    )


def test_hub_interaction_dispatch_non_abc_element_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the resolved element is a wire dataclass (not ABC) the dispatch returns."""
    from collections.abc import Mapping
    from dataclasses import dataclass
    from typing import Literal, Self

    import punt_lux.domain.hub as hub_module

    @dataclass(frozen=True, slots=True)
    class _WireLeaf:
        id: str
        kind: Literal["leaf"] = "leaf"
        tooltip: str | None = None

        def to_dict(self) -> dict[str, object]:
            return {"id": self.id, "kind": self.kind}

        @classmethod
        def from_dict(cls, d: Mapping[str, object]) -> Self:
            return cls(id=str(d["id"]))

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    owner = ConnectionId("agent")
    isolated_display.register_client(owner)
    wire_leaf = _WireLeaf(id="leaf")
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=wire_leaf, parent_id=None),
    )

    fake_registry = SimpleNamespace(get=MagicMock())
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(hub_module, "client_registry", fake_registry)

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id="scene",
            element_id="leaf",
            action="click",
            ts=1.0,
            value=True,
        )
    )

    fake_registry.get.assert_not_called()


def test_hub_interaction_dispatch_marks_dirty_without_display_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dispatch fires the handler and marks the scene dirty — never sends.

    Marking dirty is queue-only, so a click can never fail on display I/O the way
    the old inline re-push could. The replicator does the send in the background.
    """
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("confirm")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    button = ButtonElement(id=str(element_id), label="Confirm")
    fired: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: fired.append("ok"))
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    mock_replicator = MagicMock()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", mock_replicator
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="confirm",
            event_kind="button_clicked",
            ts=1.0,
            value=True,
        )
    )

    assert fired == ["ok"]
    mock_replicator.mark_dirty.assert_called_once_with(scene_id)


def test_hub_interaction_dispatch_runs_checkbox_value_changed_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("toggle")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    checkbox = CheckboxElement(id=str(element_id), label="Toggle")
    seen: list[tuple[str, bool | int | float | str]] = []

    def _handler(event: ValueChanged) -> None:
        seen.append(("handled", event.value))

    checkbox.add_handler(ValueChanged, _handler)
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=checkbox, parent_id=None),
    )

    mock_replicator = MagicMock()

    import punt_lux.domain.hub as hub_module

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", mock_replicator
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="toggle",
            event_kind="value_changed",
            ts=1.0,
            value=False,
        )
    )

    assert seen == [("handled", False)]
    mock_replicator.mark_dirty.assert_called_once_with(scene_id)


def test_hub_interaction_dispatch_unknown_event_kind_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown event_kind logs warning and returns without firing."""
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("btn")
    owner = ConnectionId("agent")
    isolated_display.register_client(owner)

    button = ButtonElement(id=str(element_id), label="OK")
    fired: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: fired.append("fired"))
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="click",
            event_kind="unknown_kind",
            ts=1.0,
            value=True,
        )
    )

    assert fired == []


def test_hub_interaction_dispatch_never_deletes_a_frames_scenes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """X8 — the Hub has no frame-close handler, because closing never reaches it.

    This is F4 of DES-065 R8, and it is the half of the fix that is invisible
    from the Display alone. The Display used to send a ``frame_close`` when the
    user clicked a frame's ✕; the Hub answered by removing the scenes that frame
    held and marking them dirty, and the replicator pushed them back **empty** —
    which is the dispose path. So even a Display that kept its closed frame
    perfectly would have had it thrown out one round trip later, by the Hub, on
    the user's own close.

    Where a window sits is the Display's business. The Hub is told nothing, and
    an action it does not recognise falls through to the element fire, where it
    resolves to nothing and is dropped. ``FrameLifecycle.remove_frame`` went
    with the handler: the TTL sweep never used it, so retiring the branch left
    it with no caller at all.
    """
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("framed")
    owner = ConnectionId("agent")
    frame_id = "f1"
    isolated_display.register_client(owner)
    isolated_display.apply(
        owner,
        AddElement(
            scene_id=scene_id,
            element=ButtonElement(id="b", label="x"),
            parent_id=None,
        ),
    )
    isolated_display.frames.present(
        scene_id, ScenePresentation(frame_id=frame_id), ttl_seconds=60.0
    )

    mock_replicator = MagicMock()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", mock_replicator
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            element_id=frame_id,
            action="frame_close",
            ts=1.0,
            value=None,
        )
    )

    assert isolated_display.scene_roots(scene_id) != []  # the content is untouched
    mock_replicator.mark_dirty.assert_not_called()
    assert isolated_display.frames.seconds_until_next() is not None  # TTL still armed


def test_frame_close_is_not_a_branch_of_the_dispatch() -> None:
    """Retired, not aliased: no handler for the action remains to be reached."""
    assert not hasattr(HubInteractionDispatch, "_close_frame")


def test_hub_interaction_dispatch_value_changed_rejects_non_scalar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-scalar value_changed payload logs and returns.

    ``value_changed`` legitimately carries a ``bool`` (checkbox), ``str``
    (input_text), or ``int``/``float`` (slider); the firing element's own setter
    re-validates the shape for its kind. A non-scalar value (here a list) is
    rejected at the hub dispatch itself.
    """
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("cb")
    owner = ConnectionId("agent")
    isolated_display.register_client(owner)

    cb = CheckboxElement(id=str(element_id), label="Toggle")
    fired: list[str] = []
    cb.add_handler(ValueChanged, lambda _e: fired.append("fired"))
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=cb, parent_id=None),
    )

    monkeypatch.setattr(hub_module, "hub_display", isolated_display)

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="changed",
            event_kind="value_changed",
            ts=1.0,
            value=[1, 2, 3],
        )
    )

    assert fired == []


def test_hub_interaction_dispatch_kindless_invocation_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A kindless (event_kind=None) invocation matches no spec and is denied.

    The old ``(None, "button_clicked")`` tolerance is gone: an invocation that
    names no kind is not a button click by default — it fits no element's spec,
    so it is denied at the boundary and the handler never runs.
    """
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    element_id = ElementId("btn")
    owner = ConnectionId("agent")
    isolated_display.register_client(owner)

    button = ButtonElement(id=str(element_id), label="OK")
    fired: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: fired.append("fired"))
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    mock_replicator = MagicMock()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", mock_replicator
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id=str(element_id),
            action="click",
            ts=1.0,
            value=True,
        )
    )

    assert fired == []
    mock_replicator.mark_dirty.assert_not_called()


def test_hub_interaction_dispatch_drops_click_on_dismissed_ancestors_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A click on a child whose ancestor was marked removed is dropped, not fired.

    Only scene-root Elements carry the Hub-owned observer that routes
    ``mark_removed`` back through ``apply`` (``SubtreeInstaller``); a non-root
    ancestor (a Dialog nested inside a Group, standing in here for any
    composite that dismisses part of its own tree without going through
    ``RemoveElement``) can flip ``_removed`` with nothing removing it from the
    index. The dispatch must still refuse to fire the child's handler.
    """
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    button = ButtonElement(id="confirm", label="Confirm")
    fired: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: fired.append("fired"))
    dialog = GroupElement(id="dialog", children=[button])
    root = GroupElement(id="root", children=[dialog])
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=root, parent_id=None),
    )

    # The dialog is a non-root ancestor: marking it removed does not cascade
    # through SubtreeInstaller's root-only observer, so it stays indexed.
    dialog.mark_removed()

    mock_replicator = MagicMock()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", mock_replicator
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id="confirm",
            action="confirm",
            event_kind="button_clicked",
            ts=1.0,
            value=True,
        )
    )

    assert fired == []
    mock_replicator.mark_dirty.assert_not_called()


def test_hub_interaction_dispatch_drops_click_on_the_dismissed_element_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A click on an element marked removed is dropped, distinct from the ancestor case.

    ``DismissalWalk.nearest_dismissed`` includes the target element itself, not
    only its ancestors — this exercises that branch directly so the two cases
    (self dismissed vs. ancestor dismissed) both have coverage.

    The button must be a NON-ROOT element, same as the ancestor-dismissed test
    above: only a scene root carries the Hub-owned observer that routes
    ``mark_removed`` through ``apply`` and drops the element from the index
    (``SubtreeInstaller``). Marking a root removed makes resolve() itself fail
    (LookupError), which drops the invocation for the wrong reason and never
    reaches ``DismissalWalk`` at all — exactly the bug Bugbot caught in an
    earlier version of this test.
    """
    import punt_lux.domain.hub as hub_module

    isolated_display = HubDisplay()
    scene_id = SceneId("scene")
    owner = ConnectionId("agent-1")
    isolated_display.register_client(owner)

    button = ButtonElement(id="confirm", label="Confirm")
    fired: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: fired.append("fired"))
    root = GroupElement(id="root", children=[button])
    isolated_display.apply(
        owner,
        AddElement(scene_id=scene_id, element=root, parent_id=None),
    )

    # button is a non-root child: marking it removed does not cascade through
    # SubtreeInstaller's root-only observer, so it stays indexed and resolve()
    # succeeds — the click must be dropped by DismissalWalk, not by a failed
    # lookup.
    button.mark_removed()

    mock_replicator = MagicMock()
    monkeypatch.setattr(hub_module, "hub_display", isolated_display)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", mock_replicator
    )

    HubInteractionDispatch.dispatch(
        RemoteEventHandlerInvocation(
            scene_id=str(scene_id),
            element_id="confirm",
            action="confirm",
            event_kind="button_clicked",
            ts=1.0,
            value=True,
        )
    )

    assert fired == []
    mock_replicator.mark_dirty.assert_not_called()
