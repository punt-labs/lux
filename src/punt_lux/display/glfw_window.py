"""Runtime attribute control for a live GLFW window, addressed by pointer."""

from __future__ import annotations

from typing import ClassVar, Self, final

from punt_lux.display.glfw_loader import GlfwLibrary


@final
class GlfwWindow:
    """Set runtime attributes on a live GLFW window addressed by pointer.

    The window address is resolved by the caller (which owns the hello_imgui
    dependency) and passed in, so this stays a pure ctypes wrapper with no
    rendering-library import. Reaching and calling the live libglfw handle is
    delegated to :class:`GlfwLibrary`, which opens the already-loaded copy
    without reloading and resolves the soname across Linux and macOS.
    """

    __slots__ = ("_address", "_library")

    _address: int
    _library: GlfwLibrary

    _GLFW_DECORATED: ClassVar[int] = 0x00020005
    _GLFW_FOCUS_ON_SHOW: ClassVar[int] = 0x0002000C

    def __new__(cls, address: int) -> Self:
        self = super().__new__(cls)
        self._address = address
        self._library = GlfwLibrary()
        return self

    def set_decorated(self, *, decorated: bool) -> None:
        """Toggle the window's title-bar decoration."""
        self._library.set_window_attrib(
            self._address, self._GLFW_DECORATED, int(decorated)
        )

    def set_opacity(self, *, opacity: float) -> None:
        """Set the window's opacity (0.0 transparent .. 1.0 opaque)."""
        self._library.set_window_opacity(self._address, opacity)

    def set_focus_on_show(self, *, focus: bool) -> None:
        """Set whether *later* ``glfwShowWindow`` calls steal keyboard focus.

        A runtime window attribute (``glfwSetWindowAttrib``), so it governs
        every reshow after the one already underway when this is called. On
        macOS, the window's *first* show after process creation cannot be
        suppressed through GLFW/HelloImGui at all — the OS activates a
        freshly-created process's first window via ``NSApplication`` before any
        attribute this call sets takes effect (display-crash-quarantine.md
        Question 3). Calling this from the Display's ``post_init`` — after
        creation, before any later reshow — is the reachable knob: it cannot
        stop the one unavoidable first-show grab, but it stops every focus
        grab on a respawned display's later reshows.
        """
        self._library.set_window_attrib(
            self._address, self._GLFW_FOCUS_ON_SHOW, int(focus)
        )
