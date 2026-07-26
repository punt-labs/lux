"""Headless doubles for asserting a leaf adapter records its painted rect.

A ``LeafRenderer`` records its geometry through the ``measuring`` group, which
reads ImGui's item-rect over the whole paint. These doubles stand in for the
ImGui vector/window API that ``GeometryCapture`` reads, so a test can drive any
leaf kind's adapter and assert the recorded rect without a GL context. Every
leaf migration (tree, plot, draw) shares them, so the painted-rect proof is one
short test body per kind over the same fixed corners.

Usage — monkeypatch ``geometry_capture.imgui`` with ``FakeGeomImgui`` and the
adapter's own ``imgui`` (and ``implot``) with a ``MagicMock``, paint through a
``GeomFactory``, then assert the recorded rect equals ``EXPECTED_RECT``.
"""

from __future__ import annotations

from typing import Self

from punt_lux.display.geometry_capture import GeometryCapture
from punt_lux.protocol.geometry import Rect

__all__ = ["EXPECTED_RECT", "FakeGeomImgui", "GeomFactory"]

# min (5, 6) .. max (105, 46) — the fixed corners FakeGeomImgui reports, giving
# a 100x40 rect at (5, 6) that every leaf adapter's paint records identically.
EXPECTED_RECT = Rect(x=5.0, y=6.0, width=100.0, height=40.0)


class GeomFactory:
    """A minimal factory exposing a real ``GeometryCapture`` and a no-op tooltip."""

    _geometry: GeometryCapture
    __slots__ = ("_geometry",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._geometry = GeometryCapture()
        return self

    @property
    def geometry(self) -> GeometryCapture:
        """Return the real capture the adapter records through."""
        return self._geometry

    def apply_tooltip(self, _elem: object) -> None:
        """No tooltip pass — the geometry record is what the test measures."""


class _Vec:
    """An ImGui vector stand-in with the ``.x``/``.y`` the geometry reads use."""

    x: float
    y: float
    __slots__ = ("x", "y")

    def __new__(cls, x: float, y: float) -> Self:
        self = super().__new__(cls)
        self.x = x
        self.y = y
        return self


class _FakeWindow:
    __slots__ = ()

    @property
    def begin_order_within_context(self) -> int:
        return 0


class _FakeInternal:
    __slots__ = ()

    def get_current_window_read(self) -> _FakeWindow:
        return _FakeWindow()


class FakeGeomImgui:
    """The ``geometry_capture`` imgui: ``end_group`` fixes the recorded rect."""

    internal: _FakeInternal
    __slots__ = ("internal",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.internal = _FakeInternal()
        return self

    def begin_group(self) -> None: ...
    def end_group(self) -> None: ...

    def get_item_rect_min(self) -> _Vec:
        return _Vec(5.0, 6.0)

    def get_item_rect_max(self) -> _Vec:
        return _Vec(105.0, 46.0)
