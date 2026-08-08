"""Domain layer — the algebra of Lux as defined in docs/architecture/domain-model.md.

This package owns the nouns of the domain (Element, Scene, Client) and the
verbs (Update, Event). It does not import imgui_bundle, json, socket, or any
other adapter. Adapters live in display/, hub/, transport/, tools/.

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
