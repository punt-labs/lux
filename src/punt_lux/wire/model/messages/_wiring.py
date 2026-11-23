"""Assemble the wire message families and their codec registry.

The facade imports these entry points without depending on each codec.
"""

from __future__ import annotations

from typing import final

from punt_lux.wire.model.messages.connect_message import ConnectMessage
from punt_lux.wire.model.messages.introspect import (
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
from punt_lux.wire.model.messages.lifecycle import (
    PROTOCOL_VERSION,
    AckMessage,
    HubManifestMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
    UnknownMessage,
    register_codecs as _register_lifecycle,
)
from punt_lux.wire.model.messages.menu import (
    CallbackMenuMessage,
    MenuMessage,
    ThemeMessage,
    register_codecs as _register_menu,
)
from punt_lux.wire.model.messages.observer import (
    ObserverMessage,
    register_codecs as _register_observer,
)
from punt_lux.wire.model.messages.registry import MessageRegistry
from punt_lux.wire.model.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.wire.model.messages.scene import SceneMessage

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
_register_remote_invocation = RemoteEventHandlerInvocation.register_codecs


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


@final
class _MessageWiring:
    """Builds a :class:`MessageRegistry` populated with every family's codecs.

    The registration step -- unlike the union assembly above -- is
    behavior, not just data (PY-OO-5): it drives seven family modules'
    ``register_codecs`` through one collaborator, so it lives on a class
    rather than as bare module-level statements.
    """

    __slots__ = ()

    @staticmethod
    def build_registry() -> MessageRegistry:
        """Return a registry with every message family's codecs installed."""
        registry = MessageRegistry()
        _register_scene(registry.register)
        _register_connect(registry.register)
        _register_lifecycle(registry.register)
        _register_remote_invocation(registry.register)
        _register_menu(registry.register)
        _register_introspect(registry.register)
        _register_observer(registry.register)
        return registry


# Use a separate MessageRegistry when isolation from the dispatch table is needed.
_registry = _MessageWiring.build_registry()

message_to_dict = _registry.to_dict
"""Encode a wire message as a dictionary, including its discriminator."""
message_from_dict = _registry.from_dict
"""Decode by discriminator; preserve unrecognized types as UnknownMessage.

Raises:
    KeyError: If a codec looks up a required field that is missing.
    ValueError: If the discriminator is invalid or a codec rejects a field value.
"""
