"""HubDisplay — facade over the Hub-side Element/owner/client store.

``HubDisplay`` is the single public surface the rest of the system
talks to for Hub-side scene state. Internally it composes five typed
collaborators, each with one responsibility:

- ``ElementIndex`` (`element_index.py`) — ``(scene_id, element_id) →
  Element`` lookup table.
- ``OwnerTracker`` (`owner_tracker.py`) — every Element's owning
  ``ConnectionId``; ``Display.interact`` gates on this, the disconnect
  path walks it to find each connection's owned roots.
- ``RootRegistry`` (`root_registry.py`) — ``(scene_id, element_id) →
  AbcElement`` for scene-root ABC Elements that participate in the
  property-Observer cascade.
- ``ChildIndex`` (`child_index.py`) — parent → children edges captured
  at install time so cascade removal can drop every descendant from the
  storage layer in one walk.
- ``HubClientRegistry`` (`hub_clients.py`) — set of connections
  currently registered as Hub clients.

``apply`` dispatches on the typed ``Update`` sum and delegates to the
collaborators. ``drop_connection`` flips ``mark_removed`` on each
ABC-root the connection owned; the Observer cascade prunes the rest of
the tree, ending with the parent composite calling
``apply(RemoveElement(...))``, which clears the index entry and fires
the next layer of observers. Wire-only (non-ABC) roots have no cascade
to drive removal — ``drop_connection`` removes them directly through
``_remove_subtree``, which walks the ``ChildIndex`` to drop every
descendant.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.child_index import ChildIndex
from punt_lux.domain.hub.element_index import (
    ElementIndex,
    UnknownElementError,
    UnknownSceneError,
)
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["HubDisplay", "UnknownElementError", "UnknownSceneError", "hub_display"]

_log = logging.getLogger(__name__)


class HubDisplay:
    """Hub-side authoritative store of Elements, owners, and clients.

    Facade over four typed collaborators. State invariants (established
    at ``apply`` time, trusted thereafter):

    - Every Element installed has a known owner ``ConnectionId``.
    - A scene-root ABC Element (``parent_id=None``) has a
      HubDisplay-owned observer registered; flipping ``_removed`` on
      the root triggers a callback into ``apply(RemoveElement(...))``.
    - Child Elements (``parent_id`` set) are observed by their parent
      composite, NOT by HubDisplay — the parent's observer is what
      drives ``apply(RemoveElement(...))`` for the child.

    Tests construct their own ``HubDisplay()``; the module exposes
    ``hub_display`` as the production singleton.
    """

    _index: ElementIndex
    _owners: OwnerTracker
    _roots: RootRegistry
    _children: ChildIndex
    _clients: HubClientRegistry

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._index = ElementIndex()
        self._owners = OwnerTracker()
        self._roots = RootRegistry()
        self._children = ChildIndex()
        self._clients = HubClientRegistry()
        return self

    # -- clients registry --------------------------------------------------

    def register_client(self, connection_id: ConnectionId) -> None:
        """Mark a connection as a known client. Idempotent."""
        self._clients.register(connection_id)

    def is_client(self, connection_id: ConnectionId) -> bool:
        """Return True if the connection is currently registered."""
        return self._clients.is_registered(connection_id)

    # -- index access ------------------------------------------------------

    def resolve(self, scene_id: SceneId, element_id: ElementId) -> WireElement:
        """Return the indexed Element or raise ``UnknownElementError``."""
        return self._index.lookup(scene_id, element_id)

    def owner_of(self, scene_id: SceneId, element_id: ElementId) -> ConnectionId:
        """Return the connection that installed the Element.

        Raises ``UnknownElementError`` if the element is not indexed —
        ownership of an absent element is meaningless.
        """
        owner = self._owners.get(scene_id, element_id)
        if owner is None:
            raise UnknownElementError(scene_id=scene_id, element_id=element_id)
        return owner

    def elements_owned_by(
        self,
        connection_id: ConnectionId,
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every ``(scene, element)`` pair this connection installed."""
        return self._owners.keys_for(connection_id)

    # -- apply -------------------------------------------------------------

    def apply(
        self,
        connection_id: ConnectionId,
        update: AddElement | SetProperty | RemoveElement,
    ) -> None:
        """Commit a state change to the index. Owner is the caller."""
        match update:
            case AddElement(scene_id=sid, parent_id=pid, element=elem):
                if pid is None:
                    self._install_scene(sid, elem, owner=connection_id)
                else:
                    self._install_child(sid, pid, elem, owner=connection_id)
            case SetProperty(scene_id=sid, element_id=eid, field=field, value=value):
                self._set_property(sid, eid, field, value)
            case RemoveElement(scene_id=sid, element_id=eid):
                self._remove_subtree(sid, eid)

    # -- cleanup trigger ---------------------------------------------------

    def drop_connection(self, connection_id: ConnectionId) -> None:
        """Forget the client and ``mark_removed`` every root it owned.

        Does NOT walk the subtree itself — that bypasses the Observer
        cascade and leaves parent composites' children tuples stale.
        Only ABC Elements participate in the cascade; wire-dataclass
        roots have no observer registry and are dropped by direct index
        cleanup at ``_remove_subtree`` time. Per-root cleanup is
        best-effort: a failure on one root is logged and the loop
        continues so a single misbehaving subtree cannot strand the
        rest of the connection's state.
        """
        self._clients.discard(connection_id)
        for scene_id, element_id in self._owners.keys_for(connection_id):
            if self._children.is_root(scene_id, element_id):
                self._drop_root(scene_id, element_id, connection_id)

    def _drop_root(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        connection_id: ConnectionId,
    ) -> None:
        """Tear down one scene-root; logs and swallows per-root failures."""
        try:
            root = self._roots.get(scene_id, element_id)
            if root is not None:
                root.mark_removed()
            else:
                self._remove_subtree(scene_id, element_id)
        except Exception:  # noqa: BLE001 — fan-out cleanup boundary; continue past failure
            _log.exception(
                "drop_connection: cleanup failed for root %s in scene %s (conn %s)",
                element_id,
                scene_id,
                connection_id,
            )

    # -- private helpers ---------------------------------------------------

    def _install_scene(
        self, scene_id: SceneId, element: WireElement, *, owner: ConnectionId
    ) -> None:
        """Install ``element`` as a scene-root under ``scene_id``."""
        element_id = ElementId(element.id)
        self._index.install_root(scene_id, element_id, element)
        self._owners.record(scene_id, element_id, owner)
        if isinstance(element, AbcElement):
            self._roots.register(scene_id, element_id, element)
            element.add_observer(self._root_observer_for(scene_id, element_id))

    def _install_child(
        self,
        scene_id: SceneId,
        parent_id: ElementId,
        element: WireElement,
        *,
        owner: ConnectionId,
    ) -> None:
        """Install ``element`` under ``parent_id``.

        Index-only wiring; the parent-as-observer is the parent
        composite's responsibility, not HubDisplay's. The parent →
        child edge is recorded so cascade removal can drop the
        descendant from storage even when the parent has no observer
        (wire-only subtrees).
        """
        element_id = ElementId(element.id)
        self._index.install_child(scene_id, parent_id, element_id, element)
        self._owners.record(scene_id, element_id, owner)
        self._children.record(scene_id, parent_id, element_id)

    def _set_property(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        field: str,
        value: object,
    ) -> None:
        """Apply a single-field patch to an indexed ABC Element.

        Wire dataclasses are frozen; ``SetProperty`` against a frozen
        Element is a programmer error and raises ``TypeError``.
        """
        element = self._index.lookup(scene_id, element_id)
        if not isinstance(element, AbcElement):
            msg = (
                f"SetProperty target {element_id!r} in scene {scene_id!r} "
                f"is not a mutable ABC Element"
            )
            raise TypeError(msg)
        element.apply_patch({field: value})

    def _remove_subtree(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Clear the element and every descendant from storage.

        Walks the ``ChildIndex`` to enumerate descendants in install
        order, then drops each in turn. For ABC subtrees the Observer
        cascade has already pruned the parent composite's children
        tuple; for wire-only subtrees no cascade exists, so this walk
        is the sole removal path. Either way, storage cleanup runs
        here so future ``resolve`` calls fail loud.
        """
        for descendant_id in self._children.descendants(scene_id, element_id):
            self._drop_storage(scene_id, descendant_id)
        self._drop_storage(scene_id, element_id)

    def _drop_storage(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop one element from every storage collaborator. Idempotent."""
        self._index.discard(scene_id, element_id)
        self._owners.discard(scene_id, element_id)
        self._roots.discard(scene_id, element_id)
        self._children.discard(scene_id, element_id)

    def _root_observer_for(
        self, scene_id: SceneId, element_id: ElementId
    ) -> Callable[[str], None]:
        """Return the observer callback for a scene-root Element.

        Fires on every property change; on ``"removed"`` it routes the
        removal back through ``apply(RemoveElement(...))`` so the index
        and the Element's lifecycle stay coupled.
        """

        def _observe(property_name: str) -> None:
            if property_name != "removed":
                return
            owner = self._owners.get(scene_id, element_id)
            if owner is None:
                return
            self.apply(owner, RemoveElement(scene_id=scene_id, element_id=element_id))

        return _observe


hub_display = HubDisplay()
