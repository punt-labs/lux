"""Define the Lux domain's identities, elements, updates, and events.

See ``docs/architecture/target/ui-model.md`` for the target UI model.
Keep element and identity types independent of ImGui, JSON, and sockets.

The surface here is identity NewTypes, the Element Protocol and its ABC, the
three Update kinds (AddElement, RemoveElement, SetProperty), and the matching
Events and Errors. The store those Updates are applied to is
``domain.hub.HubDisplay`` — the Hub is the one authority, and the domain layer
holds no second one.
"""

from __future__ import annotations

from punt_lux.domain.element import Element
from punt_lux.domain.ids import ClientId, ConnectionId, ElementId, SceneId, Topic

__all__ = [
    "ClientId",
    "ConnectionId",
    "Element",
    "ElementId",
    "SceneId",
    "Topic",
]
