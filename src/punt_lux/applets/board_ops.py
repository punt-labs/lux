"""``BoardOps`` -- the Hub-write surface a board push needs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.client.facade import LuxClient
    from punt_lux.operations import (
        OpError,
        RenderRequest,
        RenderTableRequest,
        SceneShown,
        Scope,
    )

__all__ = ["BoardOps", "ScopedBoardOps"]


@runtime_checkable
class BoardOps(Protocol):
    """The Hub-write surface a board push needs: install a scene.

    Deliberately narrow -- every applet-internal class collectively calls
    exactly these two methods, not the full ``SceneOps`` family they belong
    to Hub-side. Reached through :class:`ScopedBoardOps`, never through
    ``LuxClient.sync`` directly.
    """

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a whole scene."""
        ...

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a composed table scene."""
        ...


@final
class ScopedBoardOps:
    """A ``BoardOps`` binding one fixed :class:`Scope` to a ``SyncOps`` transport.

    Binds the scope once, at the one place the identity is known, and
    forwards every call with it filled in.
    """

    _ops: SyncOps
    _scope: Scope
    __slots__ = ("_ops", "_scope")

    def __new__(cls, ops: SyncOps, scope: Scope) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
        return self

    @classmethod
    def for_client(cls, client: LuxClient) -> Self:
        """Bind a ``LuxClient``'s own transport and scope in one call."""
        return cls(client.sync, client.scope)

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a whole scene under this adapter's bound scope."""
        del scope  # this adapter always installs under its own bound scope
        return self._ops.render(request, scope=self._scope)

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a composed table scene under this adapter's bound scope."""
        del scope
        return self._ops.render_table(request, scope=self._scope)
