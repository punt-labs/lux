"""SimulatedAgent — the driver that exercises the real client/tool surface.

The agent performs the same Hub-side operations the production MCP tools
perform (``show`` -> ``hub_element_factory`` + ``ElementTreeValidator`` +
``hub_display.replace_scene`` + the Display push; ``subscribe`` ->
``ensure_writer`` + ``hub.subscribe``; ``recv`` -> ``next_event``;
``update`` -> ``hub_display.apply`` + re-push), plus the addressable
inject. It drives the full bidirectional circle for one scenario and
returns a ``LoopObservation`` the invariants assert against.

The return path is a **closed causal chain**: the agent reacts by mutating
the UI and re-pushing ONLY when the subscribed business event was actually
delivered. If nothing arrives, the agent does not react — so I5 proves the
agent reacted *because* the event arrived, not merely that an update landed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.container_interaction import HeaderToggled, TabChanged
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub import hub, hub_display
from punt_lux.domain.ids import ClientId, ConnectionId, ElementId, SceneId, Topic
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.update import AddElement, SetProperty
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.tools.hub_factory import hub_element_factory
from punt_lux.tools.inbox import drain_inbox, ensure_writer, next_event

from .scenario import INPUT_COMMIT_TEXT, SLIDER_COMMIT_VALUE
from .target_handlers import RecordingClickHandler

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.domain.event_protocol import Event
    from punt_lux.protocol.messages.observer import ObserverMessage
    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )

    from .rig import InProcessLoop
    from .scenario import Scenario

__all__ = ["LoopObservation", "SimulatedAgent"]


@dataclass(frozen=True, slots=True)
class LoopObservation:
    """Everything one full loop run observed, for the invariants to assert.

    Captures both directions and three inspection snapshots: the replica
    after ``show`` (before the click), after dispatch (the handler-driven
    re-push already applied), and after the agent's return-path reaction.
    ``reacted`` records whether the agent reacted — gated on delivery — so
    I5 can prove the causal link.
    """

    crossed: tuple[RemoteEventHandlerInvocation, ...]
    recorder: RecordingClickHandler
    delivered: tuple[ObserverMessage, ...]
    post_show_inspection: dict[str, object]
    post_dispatch_inspection: dict[str, object]
    post_react_inspection: dict[str, object]
    reacted: bool


class SimulatedAgent:
    """One connection driving show/subscribe/inject/recv/update/inspect.

    Constructed with its own ``ConnectionId`` so two agents can prove
    connection-scoped isolation on the same live loop.
    """

    _connection_id: ConnectionId
    _rig: InProcessLoop
    _scene_id: str

    def __new__(cls, *, connection_id: str, rig: InProcessLoop) -> Self:
        self = super().__new__(cls)
        self._connection_id = ConnectionId(connection_id)
        self._rig = rig
        self._scene_id = ""
        return self

    @property
    def connection_id(self) -> ConnectionId:
        """Return this agent's connection scope."""
        return self._connection_id

    # -- the full circle ---------------------------------------------------

    def run(self, scenario: Scenario) -> LoopObservation:
        """Drive the whole bidirectional loop and return what it observed."""
        return self.run_subscribed_to(scenario, scenario.topic)

    def run_subscribed_to(
        self, scenario: Scenario, subscribe_topic: str
    ) -> LoopObservation:
        """Drive the loop while subscribed to ``subscribe_topic``.

        The normal run subscribes to the scenario's own topic. Passing a
        different topic drives the causal-gate negative case: the handler
        still publishes the scenario topic, but nothing is delivered to this
        connection, so the agent must NOT react.
        """
        recorder = self.show(scenario)
        self.subscribe(subscribe_topic)
        post_show = self.inspect(scenario.scene_id)
        crossed = self.inject(scenario.target_element_id)
        post_dispatch = self.inspect(scenario.scene_id)
        delivered = self.drain()
        reacted = bool(delivered)
        if reacted:
            self.update(scenario.scene_id, scenario.react)
        post_react = self.inspect(scenario.scene_id)
        return LoopObservation(
            crossed=crossed,
            recorder=recorder,
            delivered=delivered,
            post_show_inspection=post_show,
            post_dispatch_inspection=post_dispatch,
            post_react_inspection=post_react,
            reacted=reacted,
        )

    # -- the tool surface (production Hub-side operations) -----------------

    def show(self, scenario: Scenario) -> RecordingClickHandler:
        """Install the scene: decode, wire handlers, validate, push.

        Returns the view-logic recorder wired onto the target element so
        the caller can assert the UI-handler mechanism fired (I6). Installs
        the scenario's ``PublishSource`` — a no-op for wire-declared
        publishes, an agent-wired ``PublishingHandler`` for payload ones.
        """
        self._scene_id = scenario.scene_id
        factory = hub_element_factory(self._connection_id)
        roots = [factory.element_from_dict(e) for e in scenario.wire_elements()]
        target = self._find_target(roots, scenario.target_element_id)
        event_type = self._event_type_for(target)
        recorder = RecordingClickHandler()
        target.add_handler(event_type, recorder)
        scenario.publish.install(
            target, connection_id=str(self._connection_id), event_type=event_type
        )
        report = ElementTreeValidator().validate_tree(roots)
        assert report.ok, report.describe()
        hub_display.replace_scene(
            self._connection_id,
            SceneId(scenario.scene_id),
            cast("Sequence[DomainElement]", roots),
        )
        self._rig.push_scene(scenario.scene_id, cast("Sequence[DomainElement]", roots))
        return recorder

    def subscribe(self, topic: str) -> None:
        """Bind the inbox writer and subscribe the connection to ``topic``."""
        ensure_writer(self._connection_id)
        hub.subscribe(self._connection_id, Topic(topic))

    def inject(self, element_id: str) -> tuple[RemoteEventHandlerInvocation, ...]:
        """Fire the replica element's real handler and cross the interaction.

        Firing the wrapped Display copy drives the same ``RemoteDispatchGroup``
        a GLFW click drives, so the crossed invocation is byte-identical to a
        real click's.
        """
        element = self._rig.resolve_replica(element_id)
        element.fire(self._event_for(element))
        return self._rig.cross()

    def recv(self, timeout: float = 1.0) -> ObserverMessage | None:
        """Return the next business event on this connection's inbox, or None."""
        return next_event(self._connection_id, timeout)

    def drain(self) -> tuple[ObserverMessage, ...]:
        """Snapshot every business event delivered to this connection's inbox."""
        return drain_inbox(self._connection_id)

    def update(self, scene_id: str, react: Sequence[object]) -> None:
        """React: patch Hub authority once per patch, then re-push whole scene.

        The Hub stays authoritative — each field patch lands on the Hub copy
        via ``apply(SetProperty(...))`` — and the replica is replaced whole
        (target.md's whole-UI resend), so ``inspect_scene`` reflects the
        change only via the re-push, never a local Display edit. A realistic
        reaction is several patches (advance a bar AND relabel it), applied
        before one re-push.
        """
        from .scenario import ReactPatch

        for patch in react:
            assert isinstance(patch, ReactPatch)
            hub_display.apply(
                self._connection_id,
                SetProperty(
                    scene_id=SceneId(scene_id),
                    element_id=ElementId(patch.element_id),
                    field=patch.field,
                    value=patch.value,
                ),
            )
        roots = hub_display.scene_roots(SceneId(scene_id))
        self._rig.push_scene(scene_id, roots)

    def inspect(self, scene_id: str) -> dict[str, object]:
        """Return the Display replica's enriched ``inspect_scene`` response."""
        return self._rig.inspect(scene_id)

    def install_extra_root(self, scene_id: str, wire: Mapping[str, object]) -> None:
        """Install one extra scene-root into ``HubDisplay`` via the Hub factory.

        Decodes ``wire`` through the same connection-scoped Hub factory and
        adds it as a root this connection owns. Used by the non-ABC deny-path
        fixture to place a legacy (non-ABC) element in the store so the
        dispatch has a real non-ABC target to resolve and reject.
        """
        factory = hub_element_factory(self._connection_id)
        elem = cast("DomainElement", factory.element_from_dict(dict(wire)))
        hub_display.apply(
            self._connection_id,
            AddElement(scene_id=SceneId(scene_id), element=elem, parent_id=None),
        )

    # -- helpers -----------------------------------------------------------

    def _find_target(
        self, roots: Sequence[object], target_element_id: str
    ) -> AbcElement:
        """Return the authoritative ABC element with ``target_element_id`` or raise."""
        for root in roots:
            found = self._find(root, target_element_id)
            if found is not None:
                return found
        msg = f"target {target_element_id!r} not in composed surface"
        raise LookupError(msg)

    def _find(self, element: object, element_id: str) -> AbcElement | None:
        """Search an ABC subtree for ``element_id`` (None = not in this subtree)."""
        if not isinstance(element, AbcElement):
            return None
        if element.id == element_id:
            return element
        for child in element.child_elements():
            found = self._find(child, element_id)
            if found is not None:
                return found
        return None

    def _event_for(self, element: AbcElement) -> Event:
        """Build the typed event a real interaction on ``element`` fires.

        Placeholder identity fields match the display-tier click
        (``ButtonRenderer`` uses ``"__display__"``); the wrapped
        ``RemoteDispatchGroup`` reads only the event type, deriving the
        wire value and reusing its own captured element_id/action.
        """
        if isinstance(element, ButtonElement):
            return ButtonClicked(
                scene_id=SceneId("__display__"),
                element_id=ElementId(element.id),
                owner_id=ClientId("__display__"),
            )
        if isinstance(element, CheckboxElement):
            return ValueChanged(
                scene_id=SceneId("__display__"),
                element_id=ElementId(element.id),
                owner_id=ClientId("__display__"),
                value=not element.value,
            )
        if isinstance(element, InputTextElement):
            return ValueChanged(
                scene_id=SceneId("__display__"),
                element_id=ElementId(element.id),
                owner_id=ClientId("__display__"),
                value=INPUT_COMMIT_TEXT,
            )
        if isinstance(element, SliderElement):
            return ValueChanged(
                scene_id=SceneId("__display__"),
                element_id=ElementId(element.id),
                owner_id=ClientId("__display__"),
                value=SLIDER_COMMIT_VALUE,
            )
        if isinstance(element, CollapsingHeaderElement):
            return HeaderToggled(
                scene_id=SceneId("__display__"),
                element_id=ElementId(element.id),
                owner_id=ClientId("__display__"),
                open_=not element.open,
            )
        if isinstance(element, TabBarElement):
            return TabChanged(
                scene_id=SceneId("__display__"),
                element_id=ElementId(element.id),
                owner_id=ClientId("__display__"),
                tab_id=self._other_tab(element),
            )
        msg = f"no synthetic event for element kind of {element.id!r}"
        raise TypeError(msg)

    @staticmethod
    def _other_tab(element: TabBarElement) -> str:
        """Return a tab id different from the active one — the user's switch target."""
        for tab in element.tabs:
            if tab.tab_id != element.active_tab:
                return tab.tab_id
        msg = f"tab_bar {element.id!r} has no tab to switch to"
        raise ValueError(msg)

    def _event_type_for(self, element: AbcElement) -> type[Event]:
        """Return the interaction event type the target fires."""
        if isinstance(element, ButtonElement):
            return ButtonClicked
        if isinstance(element, CheckboxElement | InputTextElement | SliderElement):
            return ValueChanged
        if isinstance(element, CollapsingHeaderElement):
            return HeaderToggled
        if isinstance(element, TabBarElement):
            return TabChanged
        msg = f"no interaction event type for element kind of {element.id!r}"
        raise TypeError(msg)
