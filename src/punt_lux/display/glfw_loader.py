"""The process's live libglfw handle, resolved and reached across platforms."""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import ClassVar, Self, final


@final
class GlfwLibrary:
    """The already-loaded libglfw handle, opened once without reloading it.

    ``RTLD_NOLOAD`` returns the existing handle instead of mapping a second
    copy — a duplicate map triggers Objective-C class warnings on macOS — and
    is POSIX-only, so ``getattr`` falls back to ``0`` where the constant is
    absent. The soname is resolved through ``ctypes.util.find_library`` so one
    code path serves Linux and macOS; a per-platform fallback covers a stripped
    runtime whose lookup returns ``None``. The class owns both resolution and
    the thin ``glfwSetWindow*`` calls so the window wrapper never imports ctypes
    resolution details.
    """

    __slots__ = ("_lib",)

    _lib: ctypes.CDLL

    _FALLBACK_SONAMES: ClassVar[dict[str, str]] = {"darwin": "libglfw.3.dylib"}
    _DEFAULT_SONAME: ClassVar[str] = "libglfw.so.3"

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lib = ctypes.CDLL(cls._soname(), mode=getattr(ctypes, "RTLD_NOLOAD", 0))
        return self

    def set_window_attrib(self, address: int, attrib: int, value: int) -> None:
        """Set integer window ``attrib`` to ``value`` on the window at ``address``."""
        self._lib.glfwSetWindowAttrib.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._lib.glfwSetWindowAttrib(ctypes.c_void_p(address), attrib, value)

    def set_window_opacity(self, address: int, opacity: float) -> None:
        """Set the opacity of the window at ``address`` (0.0 .. 1.0)."""
        self._lib.glfwSetWindowOpacity.argtypes = [ctypes.c_void_p, ctypes.c_float]
        self._lib.glfwSetWindowOpacity(ctypes.c_void_p(address), opacity)

    @classmethod
    def _soname(cls) -> str:
        """Return libglfw's name, preferring the dynamic loader's own lookup."""
        found = ctypes.util.find_library("glfw")
        return found or cls._FALLBACK_SONAMES.get(sys.platform, cls._DEFAULT_SONAME)
