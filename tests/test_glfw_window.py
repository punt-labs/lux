"""Unit tests for GlfwWindow — the pointer wrapper that delegates to GlfwLibrary.

``GlfwLibrary`` is mocked at the ``glfw_window`` import boundary so these tests
assert only the delegation contract — that each setter forwards the window
address and the right arguments — without touching ctypes or a real libglfw.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import punt_lux.display.glfw_window as glfw_window
from punt_lux.display.glfw_window import GlfwWindow

if TYPE_CHECKING:
    import pytest


def test_construction_stores_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handle is built around the window address it is given."""
    monkeypatch.setattr(glfw_window, "GlfwLibrary", MagicMock())

    window = GlfwWindow(0xDEAD)

    assert window._address == 0xDEAD


def test_set_decorated_delegates_to_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_decorated forwards the address, attribute id, and int flag."""
    lib = MagicMock()
    monkeypatch.setattr(glfw_window, "GlfwLibrary", MagicMock(return_value=lib))

    GlfwWindow(0x1234).set_decorated(decorated=True)

    lib.set_window_attrib.assert_called_once_with(0x1234, GlfwWindow._GLFW_DECORATED, 1)


def test_set_opacity_delegates_to_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_opacity forwards the address and opacity to the library."""
    lib = MagicMock()
    monkeypatch.setattr(glfw_window, "GlfwLibrary", MagicMock(return_value=lib))

    GlfwWindow(0x1234).set_opacity(opacity=0.5)

    lib.set_window_opacity.assert_called_once_with(0x1234, 0.5)
