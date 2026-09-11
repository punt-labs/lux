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

from typing import final

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
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
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


# Module-level dispatch registry, populated at import time.  Tests that need
# isolation construct their own MessageRegistry instance directly via the
# registry sub-module.
_registry = _MessageWiring.build_registry()

# The package's codec entry points ARE the registry's own bound methods.
message_to_dict = _registry.to_dict
message_from_dict = _registry.from_dict
