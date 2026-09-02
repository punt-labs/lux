"""``client.display.*`` -- the noun-grouped Display accessor.

``mode_get``/``mode_set`` stay split rather than fused: the display fuse is
deferred to ``lux-5pwu``. Theme and window are read-only here -- setting
either is the user's own gesture at the Display's own Lux ▸ Settings menu,
never a client op (DES-088).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import (
    display_get_theme,
    display_info,
    display_mode_get,
    display_mode_set,
    display_screenshot,
    display_window_get,
)
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import (
        DisplayInfoOps,
        DisplayModeOps,
        ScreenshotOps,
        ThemeOps,
        WindowOps,
    )
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import (
        DisplayInfo,
        DisplayModeRequest,
        DisplayModeState,
        OpError,
        ThemeState,
        WindowSettings,
    )
    from punt_lux.operations.models.display_probe import Screenshot


@final
class DisplayAccessor:
    """The ``client.display.*`` verbs -- info, theme, window, mode, screenshot."""

    _info_ops: DisplayInfoOps
    _theme_ops: ThemeOps
    _window_ops: WindowOps
    _mode_ops: DisplayModeOps
    _screenshot_ops: ScreenshotOps
    _identity: ClientIdentity
    __slots__ = (
        "_identity",
        "_info_ops",
        "_mode_ops",
        "_screenshot_ops",
        "_theme_ops",
        "_window_ops",
    )

    def __new__(
        cls,
        info_ops: DisplayInfoOps,
        theme_ops: ThemeOps,
        window_ops: WindowOps,
        mode_ops: DisplayModeOps,
        screenshot_ops: ScreenshotOps,
        identity: ClientIdentity,
    ) -> Self:
        self = super().__new__(cls)
        self._info_ops = info_ops
        self._theme_ops = theme_ops
        self._window_ops = window_ops
        self._mode_ops = mode_ops
        self._screenshot_ops = screenshot_ops
        self._identity = identity
        return self

    async def info(self) -> DisplayInfo | OpError:
        """Return the display's backend, geometry, frame rate, and identity."""
        ctx: Ctx[DisplayInfoOps] = Ctx(ops=self._info_ops, identity=self._identity)
        return await display_info.execute(ctx)

    async def get_theme(self) -> ThemeState | OpError:
        """Return the active theme and the themes available to switch to."""
        ctx: Ctx[ThemeOps] = Ctx(ops=self._theme_ops, identity=self._identity)
        return await display_get_theme.execute(ctx)

    async def get_window(self) -> WindowSettings | OpError:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        ctx: Ctx[WindowOps] = Ctx(ops=self._window_ops, identity=self._identity)
        return await display_window_get.execute(ctx)

    async def get_mode(self, repo: str) -> DisplayModeState | OpError:
        """Read the display mode for ``repo``."""
        ctx: Ctx[DisplayModeOps] = Ctx(ops=self._mode_ops, identity=self._identity)
        return await display_mode_get.execute(ctx, repo)

    async def set_mode(
        self, request: DisplayModeRequest | OpError
    ) -> DisplayModeState | OpError:
        """Persist a new display mode for the requested repo."""
        ctx: Ctx[DisplayModeOps] = Ctx(ops=self._mode_ops, identity=self._identity)
        return await display_mode_set.execute(ctx, request)

    async def screenshot(self) -> Screenshot | OpError:
        """Capture the display framebuffer and return the image path."""
        ctx: Ctx[ScreenshotOps] = Ctx(ops=self._screenshot_ops, identity=self._identity)
        return await display_screenshot.execute(ctx)
