"""``client.display.*`` -- the noun-grouped Display accessor.

Theme, window, and mode are all read-only here -- setting theme or window is
the user's own gesture at the Display's own Lux ▸ Settings menu, never a
client op (DES-088); setting mode is the CLI's own direct
``DisplayModeStore`` write (``cli/display.py``), bypassing this accessor and
the Hub entirely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.commands import (
    DisplayInfoOps,
    DisplayModeOps,
    ScreenshotOps,
    ThemeOps,
    WindowOps,
    display_get_theme,
    display_info,
    display_mode_get,
    display_screenshot,
    display_window_get,
)
from punt_lux.commands._ports import Ctx
from punt_lux.commands.display_state_get import DisplayStateOps, display_state_get

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import (
        DisplayInfo,
        DisplayModeState,
        DisplayStateSnapshot,
        OpError,
        Scope,
        ThemeState,
        WindowSettings,
    )
    from punt_lux.operations.models.display_probe import Screenshot


@runtime_checkable
class _DisplayOps(
    DisplayInfoOps,
    ThemeOps,
    WindowOps,
    DisplayModeOps,
    ScreenshotOps,
    DisplayStateOps,
    Protocol,
):
    """Every ops family ``client.display.*`` reads, combined for one param.

    One real object (the REST transport) satisfies every narrower family
    already; a per-family constructor parameter each repeating that same
    object was repetition, not isolation.
    """


@final
class DisplayAccessor:
    """The ``client.display.*`` verbs: info, theme, window, mode, shot, state."""

    _ops: _DisplayOps
    _identity: ClientIdentity
    _scope: Scope
    __slots__ = ("_identity", "_ops", "_scope")

    def __new__(cls, ops: _DisplayOps, identity: ClientIdentity, scope: Scope) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        self._scope = scope
        return self

    async def info(self) -> DisplayInfo | OpError:
        """Return the display's backend, geometry, frame rate, and identity."""
        ctx: Ctx[DisplayInfoOps] = Ctx(ops=self._ops, identity=self._identity)
        return await display_info.execute(ctx)

    async def get_theme(self) -> ThemeState | OpError:
        """Return the active theme and the themes available to switch to."""
        ctx: Ctx[ThemeOps] = Ctx(ops=self._ops, identity=self._identity)
        return await display_get_theme.execute(ctx)

    async def get_window(self) -> WindowSettings | OpError:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        ctx: Ctx[WindowOps] = Ctx(ops=self._ops, identity=self._identity)
        return await display_window_get.execute(ctx)

    async def get_mode(self, repo: str) -> DisplayModeState | OpError:
        """Read the display mode for ``repo``."""
        ctx: Ctx[DisplayModeOps] = Ctx(ops=self._ops, identity=self._identity)
        return await display_mode_get.execute(ctx, repo)

    async def screenshot(self) -> Screenshot | OpError:
        """Capture the display framebuffer and return the image path."""
        ctx: Ctx[ScreenshotOps] = Ctx(ops=self._ops, identity=self._identity)
        return await display_screenshot.execute(ctx)

    async def get_state(self) -> DisplayStateSnapshot | OpError:
        """Return your own widget/frame state, for Hub-vs-Display comparison."""
        ctx: Ctx[DisplayStateOps] = Ctx(ops=self._ops, identity=self._identity)
        return await display_state_get.execute(ctx, scope=self._scope)
