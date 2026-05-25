"""Display — the authoritative scene state holder.

Holds Scenes, routes Updates from Clients, validates ownership and
typing, emits Events to subscribers. Pure domain — no ImGui, no socket,
no JSON. The single-runtime testability requirement from
``docs/architecture/domain-model.md`` §"Testability" lives here.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Self, assert_never

from punt_lux.domain._typing import field_info, replace_field, value_matches
from punt_lux.domain.element_abc import Element as ElementABC
from punt_lux.domain.error import (
    DuplicateIdError,
    Error,
    PropertyTypeError,
    UnknownElementError,
)
from punt_lux.domain.event import (
    ElementAdded,
    ElementRemoved,
    ElementUpdated,
    Event,
)
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import BUTTON_CLICKED_TOKEN, ButtonClicked
from punt_lux.domain.interaction_errors import (
    UnauthorizedInteractionError,
    UnknownClientError,
    UnknownInteractionElementError,
    UnknownInteractionSceneError,
    WrongKindError,
)
from punt_lux.domain.ownership import OwnershipError
from punt_lux.domain.snapshot import SceneSnapshot
from punt_lux.domain.subscription import Subscription
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty, Update

if TYPE_CHECKING:
    from punt_lux.domain.element import Element
    from punt_lux.protocol.messages.interaction import InteractionMessage

__all__ = ["Display", "EventCallback", "Result"]

logger = logging.getLogger(__name__)

type EventCallback = Callable[[Event], None]
type Result = Event | Error


class Display:
    """Authoritative scene state. Routes Updates → Events.

    State invariants:
      - Every Element belongs to exactly one ClientId (ownership).
      - Every Element belongs to exactly one Scene.
      - Element ids are unique within a Scene.

    Mutation discipline (PY-EH-1):
      ``apply`` validates the full Update — client exists, scene exists,
      element exists / does not exist, ownership matches, field exists,
      value type matches — before any state mutation.  On refusal it
      returns a typed ``Error`` and emits no event.  On success it
      mutates, emits one ``Event`` to every subscriber, and returns
      that same ``Event``.  Never returns ``None`` (PY-EH-8).

    Interaction discipline:
      ``interact`` is the single domain-validation site for a wire
      ``InteractionMessage``. It either constructs a typed event (today
      only ``ButtonClicked``) via the module-private factory token,
      fires it through the resolved Element's handler registry, and
      returns the event; or it raises a typed ``InteractionError``
      subclass on validation failure. The ``element.fire`` call is the
      single dispatch site downstream of ``Display.interact`` — handlers
      run exactly once, on validated input.
    """

    _clients: dict[ClientId, str]
    _scenes: dict[SceneId, dict[ElementId, Element]]
    _owners: dict[tuple[SceneId, ElementId], ClientId]
    _subscribers: list[EventCallback]
    _next_client_index: itertools.count[int]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._clients = {}
        self._scenes = {}
        self._owners = {}
        self._subscribers = []
        self._next_client_index = itertools.count(1)
        return self

    # -- topology -----------------------------------------------------------

    def connect_client(self, *, name: str) -> ClientId:
        """Register a new client and return its assigned ClientId."""
        client_id = ClientId(f"{name}-{next(self._next_client_index)}")
        self._clients[client_id] = name
        return client_id

    def disconnect_client(self, client_id: ClientId) -> tuple[ElementRemoved, ...]:
        """Remove a client and cascade-remove every Element it owns.

        Returns the sequence of ``ElementRemoved`` events emitted (for
        callers that need to drive cleanup of derived state, e.g. widget
        state caches).
        """
        if client_id not in self._clients:
            return ()
        del self._clients[client_id]
        owned = [k for k, owner in self._owners.items() if owner == client_id]
        events: list[ElementRemoved] = []
        for scene_id, element_id in owned:
            self._scenes[scene_id].pop(element_id, None)
            del self._owners[(scene_id, element_id)]
            ev = ElementRemoved(
                scene_id=scene_id, element_id=element_id, owner_id=client_id
            )
            events.append(ev)
            self._emit(ev)
        return tuple(events)

    def add_scene(self, scene_id: SceneId) -> None:
        """Register an empty scene. Idempotent — re-adding is a no-op."""
        self._scenes.setdefault(scene_id, {})

    def scene_ids(self) -> frozenset[SceneId]:
        """Return the registered scene ids."""
        return frozenset(self._scenes)

    def client_ids(self) -> frozenset[ClientId]:
        return frozenset(self._clients)

    def is_client(self, client_id: ClientId) -> bool:
        """Return whether ``client_id`` is currently registered."""
        return client_id in self._clients

    # -- pub/sub ------------------------------------------------------------

    def subscribe(self, callback: EventCallback) -> Subscription:
        """Register a success-event subscriber. Returns a cancellable handle."""
        self._subscribers.append(callback)

        def _cancel() -> None:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(callback)

        return Subscription(_cancel)

    def _emit(self, event: Event) -> None:
        """Fan an event out to every subscriber.

        Subscriber contract: callbacks should not raise.  A misbehaving
        subscriber is isolated so the remaining subscribers still see
        the event — the alternative (propagation) would let one bad
        listener block fan-out for everyone else after the state
        mutation has already happened.
        """
        for sub in list(self._subscribers):
            try:
                sub(event)
            except Exception:
                logger.exception(
                    "event subscriber raised; isolating to protect fan-out: %r",
                    sub,
                )
                continue

    # -- snapshot -----------------------------------------------------------

    def snapshot(self, scene_id: SceneId) -> SceneSnapshot:
        """Return a read-only view of the scene's current elements.

        Raises ``KeyError`` if the scene does not exist — caller's intent
        was to read a known scene; absence is an error not a value.
        """
        elements = self._scenes.get(scene_id)
        if elements is None:
            msg = f"no such scene: {scene_id!r}"
            raise KeyError(msg)
        return SceneSnapshot(scene_id, elements)

    # -- apply --------------------------------------------------------------

    def apply(self, client_id: ClientId, update: Update) -> Result:
        """Validate the Update, mutate state on success, emit and return."""
        if client_id not in self._clients:
            # Unknown client encoded as OwnershipError: one error vocabulary.
            return OwnershipError(
                scene_id=update.scene_id,
                element_id=update.target_id,
                attempting_client_id=client_id,
                owning_client_id=ClientId(""),
            )
        if update.scene_id not in self._scenes:
            return UnknownElementError(
                scene_id=update.scene_id,
                element_id=update.target_id,
            )
        # PY-EH-8: assert_never makes the type checker fail when a new Update
        # kind lands without a branch instead of silently returning None.
        match update:
            case AddElement():
                return self._apply_add(client_id, update)
            case RemoveElement():
                return self._apply_remove(client_id, update)
            case SetProperty():
                return self._apply_set(client_id, update)
            case _:
                assert_never(update)

    # -- interact -----------------------------------------------------------

    def interact(self, client_id: ClientId, msg: InteractionMessage) -> ButtonClicked:
        """Validate the wire message, construct the typed event, fire it.

        Callers must pass a wire-shape-valid message: ``msg.action`` is
        an element action (not ``"menu"`` or ``"frame_close"``) and
        ``msg.scene_id`` is not ``None``. The pump enforces those
        wire-shape preconditions before invoking this method; direct
        callers must do the same.

        Raises ``UnknownClientError`` / ``UnknownInteractionSceneError``
        / ``UnknownInteractionElementError`` /
        ``UnauthorizedInteractionError`` / ``WrongKindError`` on any
        domain validation failure. Returns the constructed
        ``ButtonClicked`` after dispatching it through the resolved
        Element's handler registry.
        """
        if not self.is_client(client_id):
            raise UnknownClientError(client_id=client_id)
        wire_scene = msg.scene_id
        if wire_scene is None:
            msg_text = "InteractionMessage.scene_id must be set before interact()"
            raise ValueError(msg_text)
        scene_id = SceneId(wire_scene)
        element_id = ElementId(msg.element_id)
        scene = self._scenes.get(scene_id)
        if scene is None:
            raise UnknownInteractionSceneError(scene_id=scene_id)
        element = scene.get(element_id)
        if element is None:
            raise UnknownInteractionElementError(
                scene_id=scene_id, element_id=element_id
            )
        owner = self._owners.get((scene_id, element_id))
        if owner != client_id:
            raise UnauthorizedInteractionError(
                scene_id=scene_id, element_id=element_id, caller=client_id
            )
        event = self._build_event(
            element=element,
            scene_id=scene_id,
            element_id=element_id,
            owner_id=client_id,
            value=msg.value,
        )
        if isinstance(element, ElementABC):
            element.fire(event)
        return event

    @staticmethod
    def _build_event(
        *,
        element: Element,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> ButtonClicked:
        """Construct the typed event for ``element``'s kind + wire ``value``.

        Currently only ``button`` + ``value is True`` produces a typed
        event. Other kinds raise ``WrongKindError`` (future PRs add
        their own typed events here).
        """
        if element.kind != "button":
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="button",
                got=element.kind,
            )
        if value is not True:
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="button click (value is True)",
                got=f"value={value!r}",
            )
        return ButtonClicked(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=owner_id,
            _token=BUTTON_CLICKED_TOKEN,
        )

    # -- per-Update handlers ------------------------------------------------

    def _apply_add(self, client_id: ClientId, update: AddElement) -> Result:
        scene = self._scenes[update.scene_id]
        element_id = ElementId(update.element.id)
        if element_id in scene:
            return DuplicateIdError(scene_id=update.scene_id, element_id=element_id)
        scene[element_id] = update.element
        self._owners[(update.scene_id, element_id)] = client_id
        event = ElementAdded(
            scene_id=update.scene_id,
            element_id=element_id,
            owner_id=client_id,
            parent_id=update.parent_id,
        )
        self._emit(event)
        return event

    def _apply_remove(self, client_id: ClientId, update: RemoveElement) -> Result:
        owner_check = self._require_ownership(
            client_id, update.scene_id, update.element_id
        )
        if owner_check is not None:
            return owner_check
        del self._scenes[update.scene_id][update.element_id]
        del self._owners[(update.scene_id, update.element_id)]
        event = ElementRemoved(
            scene_id=update.scene_id,
            element_id=update.element_id,
            owner_id=client_id,
        )
        self._emit(event)
        return event

    def _apply_set(self, client_id: ClientId, update: SetProperty) -> Result:
        owner_check = self._require_ownership(
            client_id, update.scene_id, update.element_id
        )
        if owner_check is not None:
            return owner_check
        elem = self._scenes[update.scene_id][update.element_id]
        info = field_info(elem, update.field)
        if info is None:
            return PropertyTypeError(
                scene_id=update.scene_id,
                element_id=update.element_id,
                field=update.field,
                expected_type="<field not declared>",
                got_value=update.value,
            )
        expected_name, valid_types = info
        if not value_matches(update.value, valid_types):
            return PropertyTypeError(
                scene_id=update.scene_id,
                element_id=update.element_id,
                field=update.field,
                expected_type=expected_name,
                got_value=update.value,
            )
        old_value = getattr(elem, update.field)
        new_elem = replace_field(elem, update.field, update.value)
        self._scenes[update.scene_id][update.element_id] = new_elem
        event = ElementUpdated(
            scene_id=update.scene_id,
            element_id=update.element_id,
            owner_id=client_id,
            field=update.field,
            old_value=old_value,
            new_value=update.value,
        )
        self._emit(event)
        return event

    # -- validation helpers -------------------------------------------------

    def _require_ownership(
        self,
        client_id: ClientId,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> UnknownElementError | OwnershipError | None:
        """Return the appropriate Error, or ``None`` if ownership checks out."""
        owner = self._owners.get((scene_id, element_id))
        if owner is None:
            return UnknownElementError(scene_id=scene_id, element_id=element_id)
        if owner != client_id:
            return OwnershipError(
                scene_id=scene_id,
                element_id=element_id,
                attempting_client_id=client_id,
                owning_client_id=owner,
            )
        return None
