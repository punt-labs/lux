# pyright: reportMissingModuleSource=false
"""Commands on the live application window: always-on-top, size, and quit.

The menu model says what an item does; this says how the window does it. It is
the one place the menus reach the hello_imgui runner, so the model stays a
description a test can render without a window on screen.
"""

from __future__ import annotations

from typing import Any, Protocol, final

from imgui_bundle import hello_imgui

__all__ = ["WindowChrome", "WindowChromeCommands"]

_DEFAULT_WINDOW_SIZE = (1200, 800)


class WindowChromeCommands(Protocol):
    """The window commands the display's built-in menus offer."""

    def top_most(self) -> bool:
        """Return whether the window floats above other applications."""
        ...

    def set_top_most(self, *, on: bool) -> None:
        """Float the window above other applications, or stop doing so."""

    def reset_size(self) -> None:
        """Return the window to the size Lux starts at."""

    def quit(self) -> None:
        """Ask the application to exit after this frame."""


@final
class WindowChrome:
    """Drive the running hello_imgui runner's window parameters."""

    __slots__ = ()

    def top_most(self) -> bool:
        """Return whether the window floats above other applications."""
        return bool(self._window_params().top_most)

    def set_top_most(self, *, on: bool) -> None:
        """Float the window above other applications, or stop doing so."""
        self._window_params().top_most = on

    def reset_size(self) -> None:
        """Return the window to the size Lux starts at."""
        hello_imgui.change_window_size(_DEFAULT_WINDOW_SIZE)

    def quit(self) -> None:
        """Ask the application to exit after this frame."""
        hello_imgui.get_runner_params().app_shall_exit = True

    @staticmethod
    def _window_params() -> Any:  # hello_imgui ships no stubs for AppWindowParams
        """Return the live runner's window parameters."""
        return hello_imgui.get_runner_params().app_window_params
