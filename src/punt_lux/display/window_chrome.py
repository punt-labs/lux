# pyright: reportMissingModuleSource=false
"""Commands on the live application window: always-on-top, size, and quit.

The menu model says what an item does; this says how the window does it. It is
the one place the menus reach the hello_imgui runner, so the model stays a
description a test can render without a window on screen.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Any, Protocol, Self, final

from imgui_bundle import hello_imgui

logger = logging.getLogger(__name__)

__all__ = ["WindowChrome", "WindowChromeCommands"]

_DEFAULT_WINDOW_SIZE = (1200, 800)

# The watchdog window after Quit is asked for and before the loop is
# forcibly torn down. A healthy frame lands in tens of milliseconds; five
# seconds is generous for a shutdown path (draining sockets, unlinking
# files) and short enough that a stuck loop does not force the operator
# to force-quit from Activity Monitor.
_QUIT_WATCHDOG_SECONDS = 5.0


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

    def __new__(cls) -> Self:
        return super().__new__(cls)

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
        """Ask the application to exit, and force the exit if nothing does.

        Three paths converge on the exit and each is a fallback for the
        one before it. The cooperative path sets ``app_shall_exit`` for
        the imgui loop to notice on its next iteration; SIGTERM to this
        process reaches the same flag through :class:`ExitSignal` in case
        the attribute write did not stick; and a watchdog thread calls
        ``os._exit`` after ``_QUIT_WATCHDOG_SECONDS`` in case the frame
        loop itself is wedged and never polls the flag. Without the
        watchdog a stuck display leaves the operator no in-window way
        out, which is the failure this method exists to prevent.
        """
        logger.info("Quit requested -- app_shall_exit + SIGTERM + watchdog")
        hello_imgui.get_runner_params().app_shall_exit = True
        os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(
            target=self._watchdog, name="WindowChrome.quit-watchdog", daemon=True
        ).start()

    @staticmethod
    def _watchdog() -> None:
        """Force-exit the process if a clean shutdown does not land in time."""
        time.sleep(_QUIT_WATCHDOG_SECONDS)
        logger.warning(
            "Clean exit did not land within %.1fs -- forcing os._exit",
            _QUIT_WATCHDOG_SECONDS,
        )
        os._exit(0)

    @staticmethod
    def _window_params() -> Any:  # hello_imgui ships no stubs for AppWindowParams
        """Return the live runner's window parameters."""
        return hello_imgui.get_runner_params().app_window_params
