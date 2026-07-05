"""Unit tests for GlfwWindow — the pure-ctypes live-window control wrapper.

The native libglfw call is mocked at the ``ctypes.CDLL`` boundary so the tests
run without a real GLFW window: they assert the right GLFW entry point is
invoked against the window address the handle was built with.
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.glfw_window import GlfwWindow

if TYPE_CHECKING:
    import pytest


def test_construction_stores_address() -> None:
    """The handle is built around the window address it is given."""
    window = GlfwWindow(0xDEAD)

    assert window._address == 0xDEAD


def test_set_decorated_calls_glfw_attrib(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_decorated invokes glfwSetWindowAttrib with the window address."""
    lib = MagicMock()
    monkeypatch.setattr(ctypes, "CDLL", MagicMock(return_value=lib))

    GlfwWindow(0x1234).set_decorated(decorated=True)

    lib.glfwSetWindowAttrib.assert_called_once()
    args = lib.glfwSetWindowAttrib.call_args.args
    assert args[2] == 1  # int(True)


def test_set_opacity_calls_glfw_opacity(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_opacity invokes glfwSetWindowOpacity with the requested opacity."""
    lib = MagicMock()
    monkeypatch.setattr(ctypes, "CDLL", MagicMock(return_value=lib))

    GlfwWindow(0x1234).set_opacity(opacity=0.5)

    lib.glfwSetWindowOpacity.assert_called_once()
    assert lib.glfwSetWindowOpacity.call_args.args[1] == 0.5
