"""Runtime attribute control for a live GLFW window, addressed by pointer."""

from __future__ import annotations

import ctypes
from typing import ClassVar, Self, final


@final
class GlfwWindow:
    """Set runtime attributes on a live GLFW window addressed by pointer.

    Reaches the already-loaded libglfw handle via ``RTLD_NOLOAD`` rather than
    loading a second copy, which on macOS triggers duplicate Objective-C class
    warnings. The window address is resolved by the caller (which owns the
    hello_imgui dependency) and passed in, so this stays a pure ctypes wrapper
    with no rendering-library import of its own.
    """

    __slots__ = ("_address",)

    _address: int

    _GLFW_DECORATED: ClassVar[int] = 0x00020005
    _RTLD_NOLOAD: ClassVar[int] = 0x10  # return the existing handle, do not reload
    _LIBGLFW: ClassVar[str] = "libglfw.3.dylib"

    def __new__(cls, address: int) -> Self:
        self = super().__new__(cls)
        self._address = address
        return self

    def set_decorated(self, *, decorated: bool) -> None:
        """Toggle the window's title-bar decoration."""
        lib = ctypes.CDLL(self._LIBGLFW, mode=self._RTLD_NOLOAD)
        lib.glfwSetWindowAttrib.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.glfwSetWindowAttrib(
            ctypes.c_void_p(self._address), self._GLFW_DECORATED, int(decorated)
        )

    def set_opacity(self, *, opacity: float) -> None:
        """Set the window's opacity (0.0 transparent .. 1.0 opaque)."""
        lib = ctypes.CDLL(self._LIBGLFW, mode=self._RTLD_NOLOAD)
        lib.glfwSetWindowOpacity.argtypes = [ctypes.c_void_p, ctypes.c_float]
        lib.glfwSetWindowOpacity(ctypes.c_void_p(self._address), opacity)
