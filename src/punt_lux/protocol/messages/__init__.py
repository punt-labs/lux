"""Message protocol package — wire message types and serialization dispatch.

Sub-modules house each family of message types together with their codec
helpers:

- ``scene``: scene replacement (Scene, Clear)
- ``connect_message``: the connection-identity handshake (Connect), Hub
  identity included
- ``lifecycle``: heartbeat and manifest (Ready, Ack, Ping, Pong,
  HubManifest, Unknown)
- ``remote_invocation``: handler invocations for remote execution
  (RemoteEventHandlerInvocation)
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

from punt_lux.protocol.messages.connect_message import ConnectMessage
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
    HubManifestMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
    UnknownMessage,
    register_codecs as _register_lifecycle,
)
from punt_lux.protocol.messages.menu import (
    CallbackMenuMessage,
    MenuMessage,
    ThemeMessage,
    register_codecs as _register_menu,
)
from punt_lux.protocol.messages.observer import (
    ObserverMessage,
    register_codecs as _register_observer,
)
from punt_lux.protocol.messages.registry import MessageRegistry
from punt_lux.protocol.messages.remote_invocation import (
    RemoteEventHandlerInvocation,
    register_codecs as _register_remote_invocation,
)
from punt_lux.protocol.messages.scene import (
    SceneMessage,
)

_register_scene = SceneMessage.register_codecs
_register_connect = ConnectMessage.register_codecs

__all__ = [
    "PROTOCOL_VERSION",
    "AckMessage",
    "CallbackMenuMessage",
    "ClientMessage",
    "ConnectMessage",
    "DisplayMessage",
    "HubManifestMessage",
    "IntrospectRequest",
    "IntrospectResponse",
    "ListScenesRequest",
    "ListScenesResponse",
    "MenuMessage",
    "Message",
    "MessageRegistry",
    "ObserverMessage",
    "PingMessage",
    "PongMessage",
    "QueryRequest",
    "QueryResponse",
    "ReadyMessage",
    "RemoteEventHandlerInvocation",
    "SceneMessage",
    "ScreenshotRequest",
    "ScreenshotResponse",
    "ThemeMessage",
    "UnknownMessage",
    "message_from_dict",
    "message_to_dict",
]


ClientMessage = (
    SceneMessage
    | PingMessage
    | IntrospectRequest
    | ListScenesRequest
    | ScreenshotRequest
    | MenuMessage
    | CallbackMenuMessage
    | ThemeMessage
    | ConnectMessage
    | HubManifestMessage
    | QueryRequest
)


DisplayMessage = (
    ReadyMessage
    | AckMessage
    | RemoteEventHandlerInvocation
    | ObserverMessage
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
_register_connect(_registry.register)
_register_lifecycle(_registry.register)
_register_remote_invocation(_registry.register)
_register_menu(_registry.register)
_register_introspect(_registry.register)
_register_observer(_registry.register)

# The package's codec entry points ARE the registry's own bound methods.
message_to_dict = _registry.to_dict
message_from_dict = _registry.from_dict
