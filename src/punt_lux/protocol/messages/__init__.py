"""Message protocol package — wire message types and serialization dispatch.

Sub-modules house each family of message types together with their codec
helpers:

- ``scene``: scene replacement and incremental patches (Scene, Update, Clear)
- ``lifecycle``: connection handshake and heartbeat (Ready, Connect, Ack, Ping,
  Pong, Unknown)
- ``interaction``: user-driven element events (Interaction)
- ``menu``: display configuration (Menu, RegisterMenu, Theme)
- ``introspect``: request/response pairs (Introspect, ListScenes, Screenshot,
  Query)

The ``registry`` sub-module holds the ``MessageRegistry`` class — the codec
dispatch table that maps wire ``type`` strings to (class, to_dict, from_dict)
triples.  Tests can construct isolated registries; the production registry is
the module-level ``_registry`` instance populated at import time.

This ``__init__`` is the package surface: it re-exports every public name,
assembles the ``ClientMessage`` / ``DisplayMessage`` / ``Message`` unions, and
provides ``message_to_dict`` / ``message_from_dict``.
"""

from __future__ import annotations

from typing import Any

from punt_lux.protocol.messages.interaction import (
    InteractionMessage,
    register_codecs as _register_interaction,
)
from punt_lux.protocol.messages.introspect import (
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    QueryRequest,
    QueryResponse,
    ScreenshotRequest,
    ScreenshotResponse,
    register_codecs as _register_introspect,
)
from punt_lux.protocol.messages.lifecycle import (
    PROTOCOL_VERSION,
    AckMessage,
    ConnectMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
    UnknownMessage,
    register_codecs as _register_lifecycle,
)
from punt_lux.protocol.messages.menu import (
    MenuMessage,
    RegisterMenuMessage,
    ThemeMessage,
    register_codecs as _register_menu,
)
from punt_lux.protocol.messages.registry import MessageRegistry
from punt_lux.protocol.messages.scene import (
    ClearMessage,
    SceneMessage,
    UpdateMessage,
    register_codecs as _register_scene,
)

__all__ = [
    "PROTOCOL_VERSION",
    "AckMessage",
    "ClearMessage",
    "ClientMessage",
    "ConnectMessage",
    "DisplayMessage",
    "InteractionMessage",
    "IntrospectRequest",
    "IntrospectResponse",
    "ListScenesRequest",
    "ListScenesResponse",
    "MenuMessage",
    "Message",
    "MessageRegistry",
    "PingMessage",
    "PongMessage",
    "QueryRequest",
    "QueryResponse",
    "ReadyMessage",
    "RegisterMenuMessage",
    "SceneMessage",
    "ScreenshotRequest",
    "ScreenshotResponse",
    "ThemeMessage",
    "UnknownMessage",
    "UpdateMessage",
    "message_from_dict",
    "message_to_dict",
]


ClientMessage = (
    SceneMessage
    | UpdateMessage
    | ClearMessage
    | PingMessage
    | IntrospectRequest
    | ListScenesRequest
    | ScreenshotRequest
    | MenuMessage
    | ThemeMessage
    | RegisterMenuMessage
    | ConnectMessage
    | QueryRequest
)


DisplayMessage = (
    ReadyMessage
    | AckMessage
    | InteractionMessage
    | PongMessage
    | IntrospectResponse
    | ListScenesResponse
    | ScreenshotResponse
    | QueryResponse
)
Message = ClientMessage | DisplayMessage | UnknownMessage


# Module-level dispatch registry, populated at import time.  Tests that need
# isolation construct their own MessageRegistry instance directly via the
# registry sub-module.
_registry = MessageRegistry()

_register_scene(_registry.register)
_register_lifecycle(_registry.register)
_register_interaction(_registry.register)
_register_menu(_registry.register)
_register_introspect(_registry.register)


def message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a Message dataclass to a JSON-compatible dict."""
    return _registry.to_dict(msg)


def message_from_dict(d: dict[str, Any]) -> Message:
    """Deserialize a JSON dict to the appropriate Message dataclass."""
    return _registry.from_dict(d)
