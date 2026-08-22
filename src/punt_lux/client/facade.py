"""The ``LuxClient`` facade -- the one public entry point every consumer holds.

A downstream app builds one ``LuxClient`` from its declared identity, then
reaches the Hub through noun-grouped accessors: the ``client.scene.show`` verb,
``client.topic.publish(...)``, ``client.callback.register(...)``. The facade
composes the transport (a private ``_RestTransport`` by default) once and hands
the same transport reference to every accessor so a callback registered
through one accessor is delivered through this client's listener on another.
The listener leg is built on demand from :meth:`LuxClient.listener`; a caller
that is architecturally synchronous reaches the same transport through
:attr:`LuxClient.sync` instead.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Self, final

from punt_lux.cli_identity import CliIdentity
from punt_lux.client._rest_transport import _RestTransport
from punt_lux.client.callback import CallbackAccessor
from punt_lux.client.display import DisplayAccessor
from punt_lux.client.error import ErrorAccessor
from punt_lux.client.event import EventAccessor
from punt_lux.client.frame import FrameAccessor
from punt_lux.client.menu import MenuAccessor
from punt_lux.client.scene import SceneAccessor
from punt_lux.client.session import SessionAccessor
from punt_lux.commands import ping as ping_command
from punt_lux.commands._ports import Ctx
from punt_lux.connection_identity import connection_for
from punt_lux.operations import Scope

if TYPE_CHECKING:
    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.commands._ports import PingOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.hub_client import (
        CallbackHandler,
        ConnectHandler,
        EventHandler,
        LuxHubClient,
    )
    from punt_lux.operations import OpError, Pong


@final
class LuxClient:
    """The one public entry point every downstream consumer holds.

    Construction is through :meth:`for_identity` (the daemon/app path,
    declaring an explicit ``ClientIdentity``) or :meth:`connect` (the CLI
    convenience, which derives a ``cli`` identity from the working context).
    The accessors are lazily-built properties -- one instance per accessor,
    reused for every call -- so the ``client.scene.show`` verb uses the same
    :class:`SceneAccessor` every time.
    """

    _transport: _RestTransport
    _identity: ClientIdentity
    _scope: Scope
    __slots__ = ("__dict__", "_identity", "_scope", "_transport")

    def __new__(cls, transport: _RestTransport, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        self._identity = identity
        self._scope = Scope(
            connection_for(
                {
                    "kind": identity.kind,
                    "name": identity.name,
                    "repo": identity.repo,
                    "agent": identity.agent,
                }
            )
        )
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
        """The identity this client declared."""
        return self._identity

    @property
    def scope(self) -> Scope:
        """The scope every accessor scopes writes and content reads under."""
        return self._scope

    @cached_property
    def scene(self) -> SceneAccessor:
        """The ``client.scene.*`` verbs."""
        return SceneAccessor(self._transport, self._identity, self._scope)

    @cached_property
    def frame(self) -> FrameAccessor:
        """The ``client.frame.*`` verbs."""
        return FrameAccessor(self._transport, self._identity)

    @cached_property
    def menu(self) -> MenuAccessor:
        """The ``client.menu.*`` verbs."""
        return MenuAccessor(self._transport, self._identity)

    @cached_property
    def session(self) -> SessionAccessor:
        """The ``client.session.*`` verbs."""
        return SessionAccessor(self._transport, self._identity, self._scope)

    @cached_property
    def callback(self) -> CallbackAccessor:
        """The ``client.callback.*`` verbs (``register`` only this cycle)."""
        return CallbackAccessor(self._transport, self._identity)

    @cached_property
    def display(self) -> DisplayAccessor:
        """The ``client.display.*`` verbs."""
        return DisplayAccessor(
            self._transport,
            self._transport,
            self._transport,
            self._transport,
            self._transport,
            self._identity,
        )

    @cached_property
    def event(self) -> EventAccessor:
        """The ``client.event.*`` verbs."""
        return EventAccessor(self._transport, self._identity)

    @cached_property
    def error(self) -> ErrorAccessor:
        """The ``client.error.*`` verbs."""
        return ErrorAccessor(self._transport, self._identity)

    @cached_property
    def sync(self) -> SyncOps:
        """The synchronous ops surface this client's transport already satisfies.

        For callers that are architecturally synchronous and must not create or
        join an event loop -- an applet's worker thread, dispatched via
        ``asyncio.to_thread`` specifically so it never touches the loop renewing
        its own session's lease (see ``applets/runner.py``'s module docstring).
        Returns the SAME transport instance ``scene``/``frame``/``menu``/...
        compose -- no new object, no ``asyncio.run()`` per call, no thread hop.
        Its declared type is a Protocol, never ``_RestTransport`` by name, so a
        caller can hold and pass this value without importing anything private.
        """
        return self._transport

    async def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping (top-level diagnostics verb)."""
        ctx: Ctx[PingOps] = Ctx(ops=self._transport, identity=self._identity)
        return await ping_command.execute(ctx, wait)

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
