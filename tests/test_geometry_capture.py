"""``GeometryCapture`` — the render-tier surface that reads ImGui geometry.

The window/frame reads (``record_window``/``record_frame`` → ``get_window_pos``)
need a live window and are verified at the demo gate. The ``measuring`` group,
though, has a contract testable through a fake imgui: it records the last-item
rect *after* ``end_group``, so a hover tooltip that runs inside the group cannot
poison the recorded rect. That, plus the scene-scoping and recorder handoff the
query path depends on, is covered here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Self

from punt_lux.display import geometry_capture
from punt_lux.display.geometry import GeometryRecorder
from punt_lux.display.geometry_capture import GeometryCapture
from punt_lux.protocol.geometry import Rect

if TYPE_CHECKING:
    import pytest


def test_recorder_is_a_recorder() -> None:
    assert isinstance(GeometryCapture().recorder, GeometryRecorder)


def test_complete_promotes_through_to_the_recorder() -> None:
    capture = GeometryCapture()
    # Record straight on the wrapped recorder (bypassing the ImGui read), then
    # promote through the capture — the snapshot must reflect it.
    rect = Rect(x=1.0, y=2.0, width=3.0, height=4.0)
    capture.enter_scene("s1")
    capture.recorder.record_element("s1", "e", rect, 0)
    capture.complete()
    geom = capture.recorder.snapshot().element_for("s1", "e")
    assert geom is not None
    assert geom.rect == rect


@dataclass(frozen=True, slots=True)
class _Vec:
    """An ImGui vector stand-in with the ``.x``/``.y`` the reads use."""

    x: float
    y: float


class _FakeWindow:
    """The current window read; its begin order is the leaf's stack index."""

    __slots__ = ()

    @property
    def begin_order_within_context(self) -> int:
        return 0


class _FakeInternal:
    """The ``imgui.internal`` surface ``_stack_index`` reads."""

    __slots__ = ()

    def get_current_window_read(self) -> _FakeWindow:
        return _FakeWindow()


# Three distinct rects prove which write the record read: the widget's own, the
# tooltip cursor's (the poison), and the whole group's (what end_group sets).
_WIDGET = (_Vec(0.0, 0.0), _Vec(10.0, 10.0))
_CURSOR = (_Vec(500.0, 500.0), _Vec(520.0, 510.0))
_GROUP = (_Vec(0.0, 0.0), _Vec(10.0, 40.0))


class _FakeImgui:
    """Models ImGui's last-item rect so the tooltip-poison defect is reproducible.

    ``end_group`` sets the last-item rect to the group's bounds; ``set_tooltip``
    sets it to the cursor's. ``get_item_rect_*`` report whichever ran last, as
    real ImGui does — so recording after ``end_group`` reads the group, while
    recording after a tooltip would read the cursor. ``calls`` is the ordered
    log the test asserts ``end_group`` ran after the poison.
    """

    calls: list[str]
    _min: _Vec
    _max: _Vec
    internal: ClassVar[_FakeInternal] = _FakeInternal()

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.calls = []
        self._min, self._max = _WIDGET
        return self

    def set_item(self, bounds: tuple[_Vec, _Vec]) -> None:
        self._min, self._max = bounds

    def begin_group(self) -> None:
        self.calls.append("begin_group")

    def end_group(self) -> None:
        self.calls.append("end_group")
        self.set_item(_GROUP)

    def set_tooltip(self, _text: str) -> None:
        self.calls.append("set_tooltip")
        self.set_item(_CURSOR)

    def get_item_rect_min(self) -> _Vec:
        return self._min

    def get_item_rect_max(self) -> _Vec:
        return self._max


def test_measuring_records_the_group_rect_not_a_tooltip_poison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeImgui()
    monkeypatch.setattr(geometry_capture, "imgui", fake)
    capture = GeometryCapture()
    capture.enter_scene("s")

    with capture.measuring("leaf"):
        fake.set_item(_WIDGET)  # the widget paints its own item
        fake.set_tooltip("hint")  # a hovered tooltip overwrites the last item
    capture.complete()

    # end_group ran after set_tooltip, so its whole-group bounds are the last
    # item the record read — the cursor poison is superseded, not recorded.
    assert fake.calls == ["begin_group", "set_tooltip", "end_group"]
    geom = capture.recorder.snapshot().element_for("s", "leaf")
    assert geom is not None
    assert geom.rect == Rect(x=0.0, y=0.0, width=10.0, height=40.0)
