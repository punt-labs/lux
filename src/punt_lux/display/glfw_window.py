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
