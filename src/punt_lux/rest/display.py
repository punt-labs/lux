"""The display routes — facts about, and settings of, the running display.

The Hub cannot own an ImGui theme, a window's opacity, a GPU backend string, a
framebuffer, a frame's transient minimize state, or the display's own ring
buffers. These operations proxy over luxd's one connection; the caller still
enters through a Hub operation, so there is one code path. Each handler binds its
request, calls one operation, and maps the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Query

from punt_lux.operations import (
    DisplayInfo,
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

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["DisplayRoutes"]

# Caps mirror query_dispatcher.py's ring buffers (deque maxlen 200 / 100): a
# negative count would slice a surprising subset and a larger one can never
# return more, so both are a bind-time 422.
_EventCount = Annotated[int, Query(ge=0, le=200)]
_ErrorCount = Annotated[int, Query(ge=0, le=100)]

# The display-ping wait: bounded so a caller cannot ask for a sub-100ms probe
# (unmeasurable) or a 30s+ hang. None (omitted) uses the standing display
# budget — the documented absence contract, threaded to DisplayClient.ping.
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

    def get_display_info(self) -> DisplayInfo:
        """Return the display's backend, geometry, frame rate, and identity."""
        return self._errors.respond(self._ops.get_display_info())

    def get_theme(self) -> ThemeState:
        """Return the active theme and the themes available to switch to."""
        return self._errors.respond(self._ops.get_theme())

    def set_theme(self, request: SetThemeRequest) -> ThemeState:
        """Switch the display theme and return the new theme state."""
        return self._errors.respond(self._ops.set_theme(request))

    def get_window_settings(self) -> WindowSettings:
        """Return the window's opacity, font scale, decoration, and idle rate."""
        return self._errors.respond(self._ops.get_window_settings())

    def set_window_settings(self, patch: WindowSettingsPatch) -> WindowSettings:
        """Change the provided window settings and return the new settings."""
        return self._errors.respond(self._ops.set_window_settings(patch))

    def set_frame_state(self, frame_id: str, patch: FrameStatePatch) -> Ok:
        """Change a frame's transient minimize state."""
        return self._errors.respond(self._ops.set_frame_state(frame_id, patch))

    def screenshot(self) -> Screenshot:
        """Capture the display framebuffer and return the image path."""
        return self._errors.respond(self._ops.screenshot())

    def ping(self, timeout: _PingTimeout = None) -> Pong:
        """Round-trip a ping and return the elapsed time.

        ``timeout`` bounds the display-ping wait; omitted uses the standing
        display budget.
        """
        return self._errors.respond(self._ops.ping(timeout))

    def list_recent_events(self, count: _EventCount = 50) -> RecentEvents:
        """Return the display's recent interactions, proxied."""
        return self._errors.respond(self._ops.list_recent_events(count))

    def list_errors(self, count: _ErrorCount = 20) -> RecentErrors:
        """Return the display's recent errors, proxied."""
        return self._errors.respond(self._ops.list_errors(count))
