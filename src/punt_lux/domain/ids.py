"""Identity NewTypes for the domain layer — ClientId, SceneId, ElementId."""

from __future__ import annotations

from typing import NewType

__all__ = [
    "ClientId",
    "ElementId",
    "SceneId",
]


# NewTypes carry identity through the type system without runtime overhead.
# A function expecting ClientId rejects a bare str at type-check time, which
# is the whole point — element IDs and client IDs are different nouns even
# though both are spelled str.
ClientId = NewType("ClientId", str)
SceneId = NewType("SceneId", str)
ElementId = NewType("ElementId", str)
