"""Identity NewTypes for the domain layer — ClientId, SceneId, ElementId."""

from __future__ import annotations

from typing import NewType

__all__ = [
    "ClientId",
    "ElementId",
    "SceneId",
    "Topic",
]


# NewTypes carry identity through the type system without runtime overhead.
# A function expecting ClientId rejects a bare str at type-check time, which
# is the whole point — element IDs and client IDs are different nouns even
# though both are spelled str.
ClientId = NewType("ClientId", str)
SceneId = NewType("SceneId", str)
ElementId = NewType("ElementId", str)

# Topic names the symbolic channel within a connection's scope on which
# a publish fans out to its subscribers.
Topic = NewType("Topic", str)
