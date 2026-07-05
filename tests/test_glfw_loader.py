"""Unit tests for GlfwLibrary — the pure-ctypes libglfw resolver and wrapper.

``ctypes.CDLL`` and ``ctypes.util.find_library`` are mocked at their module
boundary so the tests run without a real libglfw installed or loaded: they
assert the soname resolution order, the ``None`` fallback, and that each thin
wrapper invokes the right ``glfwSetWindow*`` entry point.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.glfw_loader import GlfwLibrary

if TYPE_CHECKING:
    import pytest


def _mock_ctypes(
    monkeypatch: pytest.MonkeyPatch, *, found: str | None
) -> tuple[MagicMock, MagicMock]:
    """Mock ``CDLL`` and ``find_library``; return the handle and the CDLL spy."""
    lib = MagicMock()
    cdll = MagicMock(return_value=lib)

    def find_library(_name: str) -> str | None:
        return found

    monkeypatch.setattr(ctypes, "CDLL", cdll)
    monkeypatch.setattr(ctypes.util, "find_library", find_library)
    return lib, cdll


def test_open_uses_find_library_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loader's own lookup wins: its soname is what CDLL is asked to open."""
    _, cdll = _mock_ctypes(monkeypatch, found="/opt/libglfw.dylib")

    GlfwLibrary()

    assert cdll.call_args.args[0] == "/opt/libglfw.dylib"


def test_open_falls_back_when_find_library_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``None`` from find_library falls back to a platform soname, never raising.

    ``find_library`` returns ``None`` on stripped runtimes and nonstandard
    installs. The loader must still resolve a name and reach ``CDLL`` — the
    boundary the mock stands in for — rather than crashing on ``None``.
    """
    _, cdll = _mock_ctypes(monkeypatch, found=None)

    GlfwLibrary()

    cdll.assert_called_once()
    assert isinstance(cdll.call_args.args[0], str)
    assert cdll.call_args.args[0]  # a non-empty soname, not None


def test_set_window_attrib_calls_glfw(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_window_attrib invokes glfwSetWindowAttrib with the passed value."""
    lib, _ = _mock_ctypes(monkeypatch, found="libglfw.so.3")

    GlfwLibrary().set_window_attrib(0x1234, 0x00020005, 1)

    lib.glfwSetWindowAttrib.assert_called_once()
    assert lib.glfwSetWindowAttrib.call_args.args[2] == 1


def test_set_window_opacity_calls_glfw(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_window_opacity invokes glfwSetWindowOpacity with the requested opacity."""
    lib, _ = _mock_ctypes(monkeypatch, found="libglfw.so.3")

    GlfwLibrary().set_window_opacity(0x1234, 0.5)

    lib.glfwSetWindowOpacity.assert_called_once()
    assert lib.glfwSetWindowOpacity.call_args.args[1] == 0.5
