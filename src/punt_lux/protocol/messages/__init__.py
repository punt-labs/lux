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
the module-level ``_registry`` instance populated at import time, inside the
internal ``_wiring`` module (below).

This ``__init__`` is the package's public surface: a thin facade re-exporting
every public name. The union assembly (``ClientMessage`` / ``DisplayMessage``
/ ``Message``) and dispatch-registry wiring live in ``_wiring`` — the one
module that actually needs an edge to every family submodule — so this
facade's own efferent coupling stays flat no matter how many message
families the package grows to (PL-CU-1).
"""

from __future__ import annotations

from punt_lux.protocol.messages._wiring import (
    PROTOCOL_VERSION,
    AckMessage,
    CallbackMenuMessage,
    ClientMessage,
    ConnectMessage,
    DisplayMessage,
    HubManifestMessage,
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    MenuMessage,
    Message,
    MessageRegistry,
    ObserverMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    ScreenshotRequest,
    ScreenshotResponse,
    ThemeMessage,
    UnknownMessage,
    message_from_dict,
    message_to_dict,
)

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
