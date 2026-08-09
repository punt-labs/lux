"""``FrameTiling`` — grid placement math, exercised with fake ImGui/region."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from punt_lux.display.frame_tiling import FrameTiling

if TYPE_CHECKING:
    from punt_lux.display.replica import Frame


@dataclass(frozen=True)
class _Vec:
    x: float
    y: float


@dataclass(frozen=True)
class _Frame:
    frame_id: str


class _FakeImgui:
    @staticmethod
    def get_cursor_screen_pos() -> _Vec:
        return _Vec(0.0, 0.0)


def _tiling(*ids: str) -> FrameTiling:
    return FrameTiling(cast("list[Frame]", [_Frame(i) for i in ids]))


def test_no_frames_yields_no_cells() -> None:
    assert _tiling().cells(_FakeImgui(), _Vec(800.0, 600.0)) == {}


def test_single_frame_fills_one_cell() -> None:
    cells = _tiling("a").cells(_FakeImgui(), _Vec(800.0, 600.0))
    assert set(cells) == {"a"}
    _x, _y, w, h = cells["a"]
    assert w > 0 and h > 0


def test_four_frames_form_a_two_by_two_grid() -> None:
    cells = _tiling("a", "b", "c", "d").cells(_FakeImgui(), _Vec(800.0, 600.0))
    assert set(cells) == {"a", "b", "c", "d"}
    # Two distinct column x-positions and two distinct row y-positions.
    xs = {round(cells[i][0], 3) for i in cells}
    ys = {round(cells[i][1], 3) for i in cells}
    assert len(xs) == 2
    assert len(ys) == 2


def test_tiny_region_floors_cell_size() -> None:
    cells = _tiling("a", "b").cells(_FakeImgui(), _Vec(10.0, 10.0))
    for _x, _y, w, h in cells.values():
        assert w >= 200.0
        assert h >= 150.0
