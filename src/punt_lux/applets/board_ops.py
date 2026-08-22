"""``BoardOps`` -- the Hub-write surface a board push needs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.operations import (
        FrameRaise,
        OpError,
        RenderRequest,
        RenderTableRequest,
        SceneShown,
        Scope,
    )

__all__ = ["BoardOps", "ScopedBoardOps"]


@runtime_checkable
class BoardOps(Protocol):
    """The Hub-write surface a board push needs: raise a frame, install a scene.

    Composed here, in the applets package, rather than as a member of
    ``client._sync_ops.SyncOps`` -- the composite belongs beside its one
    consumer (types and Protocols live in their own module, close to where
    they are read), not inside the client package that produces values
    satisfying it.

    Deliberately narrow: every applet-internal class (``BoardChannel``,
    ``ServicedClick``, ``BoardLoad``, ``BoardWork``, ``AppletService``)
    collectively calls exactly these three methods on the object it is
    handed -- not the full ``SceneOps``/``FrameOps`` families those methods
    belong to Hub-side. ``scope`` is optional here (unlike
    ``commands._ports.SceneOps``, where the in-process ``Operations`` facade
    genuinely needs it): over REST the parameter is structural conformance
    only (``RestCaller.resolve`` derives scope from the identity headers on
    every request), and an applet's board layer never owns a ``Scope`` to
    begin with -- only the leg that built the transport does. A caller
    reaches this Protocol through :class:`ScopedBoardOps`, never through
    ``LuxClient.sync`` directly -- ``SyncOps`` inherits ``SceneOps``'s
    mandatory-``scope`` Protocol signature verbatim (the annotation a
    Protocol declares, not the default its concrete implementation happens
    to carry), so it does not structurally satisfy this narrower, optional
    -scope shape.
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

    def raise_frame(self, frame_id: str) -> FrameRaise | OpError:
        """Bring a frame to the front, restoring it if it was minimized."""
        ...


@final
class ScopedBoardOps:
    """A ``BoardOps`` binding one fixed :class:`Scope` to a ``SyncOps`` transport.

    ``SyncOps.render``/``render_table`` require ``scope`` -- the Protocol
    signature ``SyncOps`` inherits from ``commands._ports.SceneOps`` -- so a
    value typed ``SyncOps`` cannot be handed to an applet-internal class
    expecting :class:`BoardOps` without one. This adapter binds the scope
    once, at the one place the identity is known (``ServiceRunner._rest``),
    and forwards every call with it already filled in; ``raise_frame`` needs
    no scope and passes straight through.
    """

    _ops: SyncOps
    _scope: Scope
    __slots__ = ("_ops", "_scope")

    def __new__(cls, ops: SyncOps, scope: Scope) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
        return self

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

    def raise_frame(self, frame_id: str) -> FrameRaise | OpError:
        """Bring a frame to the front (unscoped -- forwarded as-is)."""
        return self._ops.raise_frame(frame_id)
