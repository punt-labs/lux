"""Domain layer — the algebra of Lux as defined in docs/architecture/domain-model.md.

This package owns the nouns of the domain (Element, Scene, Client, Display)
and the verbs (Update, Event). It does not import imgui_bundle, json,
socket, or any other adapter. Adapters live in display/, hub/, transport/,
tools/.

PR 1 lands the minimum surface needed to migrate the ``basics`` element
family end-to-end: identity NewTypes, the Element Protocol, the three
Update kinds (AddElement, RemoveElement, SetProperty), the matching
success Events and failure Errors, and the Display class that routes
Updates to Events.
"""

from __future__ import annotations

from punt_lux.domain.element import Element
from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = [
    "ClientId",
    "Element",
    "ElementId",
    "SceneId",
]
