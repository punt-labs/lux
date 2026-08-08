"""``_render_single_frame`` records the frame rect at the right moment.

The frame's geometry must be captured AFTER its contents lay out, so an
auto-resized frame records this frame's final rect rather than the previous or
partial size; and a docked-but-collapsed frame — which still paints its tab —
must record too, or a visibly present frame reads as "did not paint".

These assert the call order GL-free: ``imgui`` is a parameter, so a fake stands
in for it, and ``GeometryCapture.record_frame`` and ``_render_frame_contents``
are spied to record when they run. No real ImGui call is made.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Self

from punt_lux.display import DisplayServer
from punt_lux.display.frame_placement import FramePlacement
from punt_lux.display.geometry_capture import GeometryCapture
from punt_lux.scene.frame import Frame

if TYPE_CHECKING:
    import pytest

_DEFAULT_SIZE = (800.0, 600.0)
_PLACEMENT = FramePlacement(fitting=False, tile_layout={}, default_size=_DEFAULT_SIZE)


def _make_server() -> DisplayServer:
    return DisplayServer("/tmp/test-lux-frame-timing.sock")


def _frame() -> Frame:
    return Frame(frame_id="f1", title="F", owner_fds=set(), scenes={}, scene_order=[])


class _FakeImgui:
    """A minimal ImGui stand-in scripting ``begin`` and the docked state."""

    _expanded: bool
    _docked: bool
    _order: list[str]
    __slots__ = ("_docked", "_expanded", "_order")

    Cond_ = SimpleNamespace(
        always=SimpleNamespace(value=0), first_use_ever=SimpleNamespace(value=0)
    )
    HoveredFlags_ = SimpleNamespace(root_and_child_windows=SimpleNamespace(value=0))

    def __new__(cls, *, expanded: bool, docked: bool, order: list[str]) -> Self:
        self = super().__new__(cls)
        self._expanded = expanded
        self._docked = docked
        self._order = order
        return self

    def set_next_window_pos(self, _pos: object, _cond: int) -> None: ...

    def set_next_window_size(self, _size: object, _cond: int) -> None: ...

    def begin(self, _title: str, still_open: bool, _flags: int) -> tuple[bool, bool]:
        return self._expanded, still_open

    def is_window_hovered(self, _flags: int) -> bool:
        return False

    def is_window_docked(self) -> bool:
        return self._docked

    def set_window_collapsed(self, _collapsed: bool) -> None: ...

    def end(self) -> None:
        self._order.append("end")


def _spy(
    monkeypatch: pytest.MonkeyPatch, server: DisplayServer, order: list[str]
) -> None:
    """Record when contents render and when the frame rect is captured."""

    def render_contents(*_args: object) -> None:
        order.append("contents")

    def resolve_flags(*_args: object) -> int:
        return 0

    def record_frame(_self: object, _fid: str) -> None:
        order.append("record")

    monkeypatch.setattr(server, "_render_frame_contents", render_contents)
    monkeypatch.setattr(server, "_resolve_frame_flags", resolve_flags)
    monkeypatch.setattr(GeometryCapture, "record_frame", record_frame)


def test_expanded_frame_records_after_contents_before_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _make_server()
    order: list[str] = []
    _spy(monkeypatch, server, order)
    fake = _FakeImgui(expanded=True, docked=False, order=order)

    result, _hovered = server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert result is None
    # The contents lay out first, then the final rect is recorded, then the
    # window closes — recording before contents would capture a stale size.
    assert order == ["contents", "record", "end"]


def test_docked_collapsed_frame_records_before_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _make_server()
    order: list[str] = []
    _spy(monkeypatch, server, order)
    fake = _FakeImgui(expanded=False, docked=True, order=order)

    result, _hovered = server._render_single_frame(_frame(), fake, _PLACEMENT)

    assert result is None
    # A docked-but-collapsed frame paints no contents but still records its tab
    # rect before closing.
    assert order == ["record", "end"]
