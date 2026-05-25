"""Identity NewTypes for the domain layer — ClientId, SceneId, ElementId."""

from __future__ import annotations

from typing import NewType

__all__ = [
    "ClientId",
    "ConnectionId",
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

# ConnectionId names a single live wire — an MCP session or an applet
# TCP connection. Subscriptions, queued messages, and writer registrations
# are all scoped by ConnectionId. Topic names the symbolic channel within
# a connection's scope on which a publish fans out to its subscribers.
ConnectionId = NewType("ConnectionId", str)
Topic = NewType("Topic", str)
