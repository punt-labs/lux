"""The display-family wire methods :class:`_RestTransport` composes and delegates to.

Splits the display-info/theme/window/mode cluster out of ``_rest_transport.py``
so that module stays under its size target. Shares one
:class:`~punt_lux.rest_transport.HttpTransport` and one identity header set
with the composing client; :class:`_DisplayRestOps` never constructs its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final
from urllib.parse import urlencode

from punt_lux.operations import (
    DisplayInfo,
    DisplayModeState,
    OpError,
    Screenshot,
    ThemeState,
    WindowSettings,
)
from punt_lux.rest_http_call import HttpCall
from punt_lux.rest_reply import RestReply

if TYPE_CHECKING:
    from punt_lux.operations import DisplayModeRequest
    from punt_lux.rest_transport import HttpTransport

__all__ = ["_DisplayRestOps"]


@final
class _DisplayRestOps:
    """Wraps the ``/display`` and ``/display-mode`` REST routes."""

    _transport: HttpTransport
    _headers: dict[str, str]
    __slots__ = ("_headers", "_transport")

    def __new__(cls, transport: HttpTransport, headers: dict[str, str]) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        self._headers = headers
        return self

    def get_display_info(self) -> DisplayInfo | OpError:
        """Return the display's backend/geometry through ``GET /display``."""
        call = HttpCall.read("/display", self._headers)
        return RestReply(self._transport.request(call)).read(DisplayInfo)

    def get_theme(self) -> ThemeState | OpError:
        """Return the active theme through ``GET /display/theme``."""
        call = HttpCall.read("/display/theme", self._headers)
        return RestReply(self._transport.request(call)).read(ThemeState)

    def get_window_settings(self) -> WindowSettings | OpError:
        """Return the window's settings through ``GET /display/window``."""
        call = HttpCall.read("/display/window", self._headers)
        return RestReply(self._transport.request(call)).read(WindowSettings)

    def read_display_mode(self, repo: str) -> DisplayModeState | OpError:
        """Read a project's display mode through ``GET /display-mode``."""
        query = urlencode({"repo": repo})
        call = HttpCall.read(f"/display-mode?{query}", self._headers)
        return RestReply(self._transport.request(call)).read(DisplayModeState)

    def write_display_mode(
        self, request: DisplayModeRequest | OpError
    ) -> DisplayModeState | OpError:
        """Write a project's display mode through ``PUT /display-mode``."""
        if isinstance(request, OpError):
            return request
        call = HttpCall.write("/display-mode", request, self._headers)
        return RestReply(self._transport.request(call)).read(DisplayModeState)

    def screenshot(self) -> Screenshot | OpError:
        """Capture the display framebuffer through ``GET /display/screenshot``."""
        call = HttpCall.read("/display/screenshot", self._headers)
        return RestReply(self._transport.request(call)).read(Screenshot)
