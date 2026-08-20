"""The display routes -- proxy display-process facts over luxd's one connection."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends, Query

from punt_lux.commands import (
    Ctx as CommandCtx,
    DisplayInfoOps,
    ErrorOps,
    EventOps,
    FrameOps,
    PingOps,
    ScreenshotOps,
    ThemeOps,
    WindowOps,
    display_get_theme as display_get_theme_command,
    display_info as display_info_command,
    display_screenshot as display_screenshot_command,
    display_set_theme as display_set_theme_command,
    display_window_get as display_window_get_command,
    display_window_set as display_window_set_command,
    error_ls as error_ls_command,
    event_ls as event_ls_command,
    frame_set_state as frame_set_state_command,
    ping as ping_command,
)
from punt_lux.operations import (
    DisplayInfo,
    FrameRaise,
    FrameStatePatch,
    Ok,
    Pong,
    RecentErrors,
    RecentEvents,
    Screenshot,
    SetThemeRequest,
    ThemeState,
    WindowSettings,
    WindowSettingsPatch,
)
from punt_lux.rest.identity import resolve_identity

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

_CallerIdentity = Annotated["ClientIdentity", Depends(resolve_identity)]

__all__ = ["DisplayRoutes"]

# Caps mirror display/query_dispatcher.py's ring buffers (deque maxlen 200 / 100): a
# negative count would slice a surprising subset and a larger one can never
# return more, so both are a bind-time 422.
_EventCount = Annotated[int, Query(ge=0, le=200)]
_ErrorCount = Annotated[int, Query(ge=0, le=100)]

# The display-ping wait: bounded so a caller cannot ask for a sub-100ms probe
# (unmeasurable) or a 30s+ hang. None (omitted) uses the standing display
# budget — the documented absence contract, threaded to DisplayLink.ping.
_PingTimeout = Annotated[float | None, Query(ge=0.1, le=30.0)]


@final
class DisplayRoutes:
    """Routes that proxy display-process facts over luxd's one connection."""

    _ops: Operations
    _errors: HttpErrorMap
    _router: APIRouter
    __slots__ = ("_errors", "_ops", "_router")

    def __new__(cls, ops: Operations, errors: HttpErrorMap) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._errors = errors
        # Route names default to each endpoint's own name, which is what the
        # explicit names here always were — so they are omitted.
        router = APIRouter(tags=["display"])
        router.add_api_route("/display", self.get_display_info, methods=["GET"])
        router.add_api_route("/display/theme", self.get_theme, methods=["GET"])
        router.add_api_route("/display/theme", self.set_theme, methods=["PUT"])
        router.add_api_route(
            "/display/window", self.get_window_settings, methods=["GET"]
        )
        router.add_api_route(
            "/display/window", self.set_window_settings, methods=["PATCH"]
        )
        router.add_api_route(
            "/display/frames/{frame_id}", self.set_frame_state, methods=["PATCH"]
        )
        router.add_api_route(
            "/display/frames/{frame_id}/raise", self.raise_frame, methods=["POST"]
        )
        router.add_api_route(
            "/display/frames/{frame_id}/close", self.close_frame, methods=["POST"]
        )
        router.add_api_route(
            "/display/frames/{frame_id}/expire", self.expire_frame, methods=["POST"]
        )
        router.add_api_route("/display/screenshot", self.screenshot, methods=["GET"])
        router.add_api_route("/display/ping", self.ping, methods=["GET"])
        router.add_api_route("/events", self.list_recent_events, methods=["GET"])
        router.add_api_route("/errors", self.list_errors, methods=["GET"])
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def get_display_info(self, identity: _CallerIdentity) -> DisplayInfo:
        """Return the display's backend, geometry, frame rate, and identity."""
        ctx: CommandCtx[DisplayInfoOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(asyncio.run(display_info_command.execute(ctx)))

    def get_theme(self, identity: _CallerIdentity) -> ThemeState:
        """Return the active theme and the themes available to switch to."""
        ctx: CommandCtx[ThemeOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(asyncio.run(display_get_theme_command.execute(ctx)))

    def set_theme(
        self, request: SetThemeRequest, identity: _CallerIdentity
    ) -> ThemeState:
        """Switch the display theme and return the new theme state."""
        ctx: CommandCtx[ThemeOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(
            asyncio.run(display_set_theme_command.execute(ctx, request))
        )

    def get_window_settings(self, identity: _CallerIdentity) -> WindowSettings:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        ctx: CommandCtx[WindowOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(
            asyncio.run(display_window_get_command.execute(ctx))
        )

    def set_window_settings(
        self, patch: WindowSettingsPatch, identity: _CallerIdentity
    ) -> WindowSettings:
        """Change the provided window settings and return the new settings."""
        ctx: CommandCtx[WindowOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(
            asyncio.run(display_window_set_command.execute(ctx, patch))
        )

    def set_frame_state(
        self, frame_id: str, patch: FrameStatePatch, identity: _CallerIdentity
    ) -> Ok:
        """Change a frame's transient minimize state."""
        ctx: CommandCtx[FrameOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(
            asyncio.run(frame_set_state_command.execute(ctx, frame_id, patch))
        )

    def raise_frame(self, frame_id: str) -> FrameRaise:
        """Bring a frame to the front, restoring it if it was minimized."""
        return self._errors.respond(self._ops.raise_frame(frame_id))

    def close_frame(self, frame_id: str) -> Ok:
        """Close a frame: tear down its scenes and disarm its TTL."""
        return self._errors.respond(self._ops.close_frame(frame_id))

    def expire_frame(self, frame_id: str) -> Ok:
        """Force a frame's TTL to expire now, tearing down its scenes."""
        return self._errors.respond(self._ops.expire_frame(frame_id))

    def screenshot(self, identity: _CallerIdentity) -> Screenshot:
        """Refuse the screenshot: framebuffer capture is unsupported (DES-028)."""
        ctx: CommandCtx[ScreenshotOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(
            asyncio.run(display_screenshot_command.execute(ctx))
        )

    async def ping(
        self, identity: _CallerIdentity, timeout: _PingTimeout = None
    ) -> Pong:
        """Round-trip a ping via PingCommand and return the typed result.

        A ping never owns Hub state, so a caller with no ``X-Lux-Client-*``
        declaration is not challenged the way a write is — ``resolve_identity``
        resolves to ``ANONYMOUS_REST`` rather than luxd's own identity, honestly
        distinct from every real caller.
        """
        ctx: CommandCtx[PingOps] = CommandCtx(ops=self._ops, identity=identity)
        result = await ping_command.execute(ctx, timeout)
        return self._errors.respond(result)

    def list_recent_events(
        self, identity: _CallerIdentity, count: _EventCount = 50
    ) -> RecentEvents:
        """Return the display's recent interactions, proxied."""
        ctx: CommandCtx[EventOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(asyncio.run(event_ls_command.execute(ctx, count)))

    def list_errors(
        self, identity: _CallerIdentity, count: _ErrorCount = 20
    ) -> RecentErrors:
        """Return the display's recent errors, proxied."""
        ctx: CommandCtx[ErrorOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(asyncio.run(error_ls_command.execute(ctx, count)))
