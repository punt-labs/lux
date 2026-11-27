"""Access the Lux Hub through a single identity-bound Python client.

Use noun-grouped methods such as ``client.scene.show``. A callback registered
by the client is delivered through a listener made by that same client.
"""

from __future__ import annotations

import asyncio
from functools import cached_property
from typing import TYPE_CHECKING, Self, final

from punt_lux.client._rest_transport import _RestTransport
from punt_lux.client.callback import CallbackAccessor
from punt_lux.client.cli_identity import CliIdentity
from punt_lux.client.display import DisplayAccessor
from punt_lux.client.error import ErrorAccessor
from punt_lux.client.event import EventAccessor
from punt_lux.client.frame import FrameAccessor
from punt_lux.client.menu import MenuAccessor
from punt_lux.client.scene import SceneAccessor
from punt_lux.client.service import ServiceAccessor
from punt_lux.client.session import SessionAccessor
from punt_lux.wire.operations import Scope

if TYPE_CHECKING:
    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.client.hub_client import (
        CallbackHandler,
        ConnectHandler,
        EventHandler,
        LuxHubClient,
    )
    from punt_lux.wire.model.client_identity import ClientIdentity
    from punt_lux.wire.operations import OpError, Pong


@final
class LuxClient:
    """Access the Hub and subscribe to events under a single identity.

    Construction is through :meth:`for_identity` (the daemon/app path, an
    explicit ``ClientIdentity``) or :meth:`connect` (the CLI convenience,
    deriving a ``cli`` identity from the working context). Accessors are
    lazily-built properties, one instance reused for every call.
    """

    _transport: _RestTransport
    _identity: ClientIdentity
    _scope: Scope
    __slots__ = ("__dict__", "_identity", "_scope", "_transport")

    def __new__(cls, transport: _RestTransport, identity: ClientIdentity) -> Self:
        """Bind the transport and scope to the supplied identity."""
        self = super().__new__(cls)
        self._transport = transport
        self._identity = identity
        self._scope = Scope.client_side(identity.connection_id)
        return self

    @classmethod
    def for_identity(cls, identity: ClientIdentity, *, timeout: float = 2.0) -> Self:
        """Build a client for a daemon or app that declares an EXPLICIT identity."""
        return cls(_RestTransport.for_identity(identity, timeout=timeout), identity)

    @classmethod
    def connect(cls, *, timeout: float = 2.0) -> Self:
        """Build a CLI-shaped client whose identity comes from the working context."""
        identity = CliIdentity.resolve()
        return cls.for_identity(identity, timeout=timeout)

    @property
    def identity(self) -> ClientIdentity:
        """Return the identity this client declared."""
        return self._identity

    @property
    def scope(self) -> Scope:
        """Return the scope used for writes and content reads."""
        return self._scope

    @cached_property
    def scene(self) -> SceneAccessor:
        """The ``client.scene.*`` verbs."""
        return SceneAccessor(self._transport, self._scope)

    @cached_property
    def frame(self) -> FrameAccessor:
        """The ``client.frame.*`` verbs."""
        return FrameAccessor(self._transport, self._identity, self._scope)

    @cached_property
    def menu(self) -> MenuAccessor:
        """The ``client.menu.*`` verbs."""
        return MenuAccessor(self._transport, self._scope)

    @cached_property
    def session(self) -> SessionAccessor:
        """The ``client.session.*`` verbs."""
        return SessionAccessor(self._transport, self._scope)

    @cached_property
    def callback(self) -> CallbackAccessor:
        """Return the accessor for menu callback registration."""
        return CallbackAccessor(self._transport, self._identity)

    @cached_property
    def service(self) -> ServiceAccessor:
        """The ``client.service.*`` verbs."""
        return ServiceAccessor.over(self._transport)

    @cached_property
    def display(self) -> DisplayAccessor:
        """The ``client.display.*`` verbs."""
        return DisplayAccessor(self._transport, self._scope)

    @cached_property
    def event(self) -> EventAccessor:
        """The ``client.event.*`` verbs."""
        return EventAccessor(self._transport)

    @cached_property
    def error(self) -> ErrorAccessor:
        """The ``client.error.*`` verbs."""
        return ErrorAccessor(self._transport)

    @cached_property
    def sync(self) -> SyncOps:
        """The sync ops surface for callers that must not touch an event loop.

        Returns the SAME transport ``scene``/``frame``/``menu``/... compose --
        no new object, no ``asyncio.run()``, no thread hop -- typed as a
        Protocol so a caller never imports ``_RestTransport`` by name.
        """
        return self._transport

    async def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping (top-level diagnostics verb)."""
        return await asyncio.to_thread(self._transport.ping, wait)

    def listener(
        self,
        *,
        on_callback: CallbackHandler,
        on_event: EventHandler,
        on_connect: ConnectHandler | None = None,
    ) -> LuxHubClient:
        """Build a persistent listen client that shares this client's identity."""
        return self._transport.listener(
            on_callback=on_callback, on_event=on_event, on_connect=on_connect
        )
