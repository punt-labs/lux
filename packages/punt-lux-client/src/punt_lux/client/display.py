"""``client.display.*`` -- the noun-grouped Display accessor.

Theme, window, and mode are all read-only here -- setting theme or window is
the user's own gesture at the Display's own Lux ▸ Settings menu, never a
client op (DES-088); setting mode is the CLI's own direct
``DisplayModeStore`` write (``cli/display.py``), bypassing this accessor and
the Hub entirely.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.wire.ops import (
    DisplayInfoOps,
    DisplayModeOps,
    ScreenshotOps,
    ThemeOps,
    WindowOps,
)
from punt_lux.wire.ops.display_state import DisplayStateOps

if TYPE_CHECKING:
    from punt_lux.wire.operations import (
        DisplayInfo,
        DisplayModeState,
        DisplayStateSnapshot,
        OpError,
        Scope,
        ThemeState,
        WindowSettings,
    )
    from punt_lux.wire.operations.display_probe import Screenshot


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
    """Query the display's configuration and state or capture a screenshot."""

    _ops: _DisplayOps
    _scope: Scope
    __slots__ = ("_ops", "_scope")

    def __new__(cls, ops: _DisplayOps, scope: Scope) -> Self:
        """Bind display operations to the caller's identity and scope."""
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
        return self

    async def info(self) -> DisplayInfo | OpError:
        """Return the display's backend, geometry, frame rate, and identity."""
        return await asyncio.to_thread(self._ops.get_display_info)

    async def get_theme(self) -> ThemeState | OpError:
        """Return the active theme and the themes available to switch to."""
        return await asyncio.to_thread(self._ops.get_theme)

    async def get_window(self) -> WindowSettings | OpError:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        return await asyncio.to_thread(self._ops.get_window_settings)

    async def get_mode(self, repo: str) -> DisplayModeState | OpError:
        """Read the display mode for ``repo``."""
        return await asyncio.to_thread(self._ops.read_display_mode, repo)

    async def screenshot(self) -> Screenshot | OpError:
        """Capture the display framebuffer and return the image path."""
        return await asyncio.to_thread(self._ops.screenshot)

    async def get_state(self) -> DisplayStateSnapshot | OpError:
        """Return your own widget/frame state, for Hub-vs-Display comparison."""
        return await asyncio.to_thread(self._ops.get_display_state, scope=self._scope)
