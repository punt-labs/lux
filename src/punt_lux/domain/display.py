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
from typing import Self, assert_never

from punt_lux.domain._display_helpers import DisplayHelpers
from punt_lux.domain._typing import replace_field, value_matches
from punt_lux.domain.element import Element
from punt_lux.domain.error import (
    DuplicateIdError,
    Error,
    PropertyTypeError,
    UnknownElementError,
)
from punt_lux.domain.event import (
    ButtonPressed,
    ElementAdded,
    ElementRemoved,
    ElementUpdated,
    Event,
)
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, Interaction
from punt_lux.domain.ownership import OwnershipError
from punt_lux.domain.snapshot import SceneSnapshot
from punt_lux.domain.subscription import Subscription
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty, Update

__all__ = ["Display", "EventCallback", "Result"]

_log = logging.getLogger(__name__)

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

        Subscriber contract: callbacks must not raise.  If one does, the
        exception propagates up through ``apply`` — the state mutation
        has already happened but the caller will observe the raise.
        Callers that need isolation wrap their callback themselves.
        """
        for sub in list(self._subscribers):
            sub(event)

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
                element_id=DisplayHelpers.update_target_id(update),
                attempting_client_id=client_id,
                owning_client_id=ClientId(""),
            )
        if update.scene_id not in self._scenes:
            return UnknownElementError(
                scene_id=update.scene_id,
                element_id=DisplayHelpers.update_target_id(update),
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

    def interact(self, client_id: ClientId, interaction: Interaction) -> Result:
        """Validate user Interaction, emit Event on success — never returns None."""
        if client_id not in self._clients:
            return OwnershipError(
                scene_id=interaction.scene_id,
                element_id=interaction.element_id,
                attempting_client_id=client_id,
                owning_client_id=ClientId(""),
            )
        if interaction.scene_id not in self._scenes:
            return UnknownElementError(
                scene_id=interaction.scene_id,
                element_id=interaction.element_id,
            )
        match interaction:
            case ButtonClicked():
                owner_check = self._require_ownership(
                    client_id, interaction.scene_id, interaction.element_id
                )
                if owner_check is not None:
                    return owner_check
                # Bugbot MED (PR #187): ButtonClicked targeting a non-button
                # element (slider, checkbox, …) would still emit ButtonPressed
                # without this kind check — a domain-level Protocol violation.
                # The pump's _is_button_click already filters at the wire
                # boundary; this is defense-in-depth for any direct caller
                # (test code, future server-side synthesis).
                elem = self._scenes[interaction.scene_id][interaction.element_id]
                if elem.kind != "button":
                    return PropertyTypeError(
                        scene_id=interaction.scene_id,
                        element_id=interaction.element_id,
                        field="kind",
                        expected_type="button",
                        got_value=elem.kind,
                    )
                event = ButtonPressed(
                    scene_id=interaction.scene_id,
                    element_id=interaction.element_id,
                    owner_id=client_id,
                )
                self._emit(event)
                return event
            case _:
                assert_never(interaction)

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
        info = DisplayHelpers.field_info(elem, update.field)
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
