"""SimulatedAgent — the driver that exercises the real client/tool surface.

The agent performs the same Hub-side operations the production MCP tools
perform (``show`` -> ``hub_element_factory`` + ``ElementTreeValidator`` +
``hub_display.replace_scene`` + the Display push; ``subscribe`` ->
``ensure_writer`` + ``hub.subscribe``; ``recv`` -> ``next_event``;
``update`` -> ``hub_display.apply`` + re-push), plus the addressable
inject. It drives the full bidirectional circle for one scenario and
returns a ``LoopObservation`` the invariants assert against.

The return path — the agent reacting to the published event by mutating
the UI and re-pushing — is a first-class step here, not a footnote.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub import hub, hub_display
from punt_lux.domain.ids import ClientId, ConnectionId, ElementId, SceneId, Topic
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.update import SetProperty
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.tools.hub_factory import hub_element_factory
from punt_lux.tools.inbox import drain_inbox, ensure_writer, next_event

from .recording_handler import RecordingClickHandler

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.domain.event_protocol import Event
    from punt_lux.protocol.messages.observer import ObserverMessage
    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )

    from .rig import InProcessLoop
    from .scenario import ReactStep, Scenario

__all__ = ["LoopObservation", "SimulatedAgent"]


@dataclass(frozen=True, slots=True)
class LoopObservation:
    """Everything one full loop run observed, for the invariants to assert.

    Captures both directions: the outbound interaction and its Hub-side
    effects, and the inbound business event plus the return-path replica
    state after the agent reacted.
    """

    crossed: tuple[RemoteEventHandlerInvocation, ...]
    recorder: RecordingClickHandler
    delivered: tuple[ObserverMessage, ...]
    pre_react_inspection: dict[str, object]
    post_react_inspection: dict[str, object]


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

    # -- the full circle ---------------------------------------------------

    def run(self, scenario: Scenario) -> LoopObservation:
        """Drive the whole bidirectional loop and return what it observed."""
        recorder = self.show(scenario)
        self.subscribe(scenario.topic)
        crossed = self.inject(scenario.target_element_id)
        delivered = self.drain()
        pre = self.inspect(scenario.scene_id)
        self.update(scenario.scene_id, scenario.react)
        post = self.inspect(scenario.scene_id)
        return LoopObservation(
            crossed=crossed,
            recorder=recorder,
            delivered=delivered,
            pre_react_inspection=pre,
            post_react_inspection=post,
        )

    # -- the tool surface (production Hub-side operations) -----------------

    def show(self, scenario: Scenario) -> RecordingClickHandler:
        """Install the scene: decode, wire handlers, validate, push.

        Returns the view-logic recorder wired onto the target element so
        the caller can assert the UI-handler mechanism fired (I6).
        """
        self._scene_id = scenario.scene_id
        factory = hub_element_factory(self._connection_id)
        roots = [factory.element_from_dict(e) for e in scenario.wire_elements()]
        recorder = self._wire_view_logic(roots, scenario.target_element_id)
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

    def update(self, scene_id: str, react: ReactStep) -> None:
        """React: patch Hub authority, then re-push the whole scene.

        The Hub stays authoritative — the field patch lands on the Hub copy
        via ``apply(SetProperty(...))`` — and the replica is replaced whole
        (target.md's whole-UI resend), so ``inspect_scene`` reflects the
        change only via the re-push, never a local Display edit.
        """
        hub_display.apply(
            self._connection_id,
            SetProperty(
                scene_id=SceneId(scene_id),
                element_id=ElementId(react.element_id),
                field=react.field,
                value=react.value,
            ),
        )
        roots = hub_display.scene_roots(SceneId(scene_id))
        self._rig.push_scene(scene_id, roots)

    def inspect(self, scene_id: str) -> dict[str, object]:
        """Return the Display replica's enriched ``inspect_scene`` response."""
        return self._rig.inspect(scene_id)

    # -- helpers -----------------------------------------------------------

    def _wire_view_logic(
        self, roots: Sequence[object], target_element_id: str
    ) -> RecordingClickHandler:
        """Register the view-logic recorder on the target's click bucket.

        The wire ``publish`` sugar already installed the pub-sub half; this
        adds the UI half as a second handler so the two mechanisms are
        asserted independently (I6). Both fire once on one Hub dispatch.
        """
        target = self._find_target(roots, target_element_id)
        recorder = RecordingClickHandler()
        target.add_handler(ButtonClicked, recorder)
        return recorder

    def _find_target(self, roots: Sequence[object], element_id: str) -> AbcElement:
        """Return the authoritative ABC element with ``element_id`` or raise."""
        for root in roots:
            found = self._find(root, element_id)
            if found is not None:
                return found
        msg = f"target {element_id!r} not in composed surface"
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
        msg = f"no synthetic event for element kind of {element.id!r}"
        raise TypeError(msg)
