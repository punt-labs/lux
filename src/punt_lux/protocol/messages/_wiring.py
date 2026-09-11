"""Wire-protocol assembly -- unions and dispatch registry for every family.

Internal to the ``messages`` package (leading underscore -- not part of the
public surface): this is the "assemble every family into one dispatch
table" concern the package facade (``__init__.py``) delegates to, per
PL-CU-1's prescribed remedy for a module that would otherwise need to
import every family submodule directly just to build its re-export
surface. Adding a new message family only ever grows this module's
efferent coupling, never the facade's.
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
from punt_lux.protocol.messages.scene import SceneMessage

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

_register_scene = SceneMessage.register_codecs
_register_connect = ConnectMessage.register_codecs


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
