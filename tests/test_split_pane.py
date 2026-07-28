"""The draggable grid/detail split: ratio store, render order, and geometry.

Headless coverage for the two-pane split. The store owns the Display-local
divider ratio in per-scene ``WidgetState`` — clamped, isolated per scene, and
durable across a re-push. ``SplitPaneElement`` drives a ``SplitPaneRenderer`` in
top → divider → bottom order and rejects a plain renderer. A geometry double
proves the fixed relationship the real ImGui splitter must keep: the grid rect
sits above the divider, which sits above the detail rect, with no overlap. The
live drag itself is a Level-6 visual check.
"""

from __future__ import annotations

from typing import Self, cast

import pytest

from punt_lux.display.renderers.imgui.split_ratio_store import SplitRatioStore
from punt_lux.protocol.elements.split_pane import SplitPaneElement, SplitPaneRenderer
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderer import Renderer
from punt_lux.scene.widget_state import WidgetState

# -- builders ---------------------------------------------------------------


def _split(default_ratio: float = 0.6) -> SplitPaneElement:
    """Build a split pane over two text panes."""
    return SplitPaneElement(
        id="sp",
        top=TextElement(id="grid", content="grid"),
        bottom=TextElement(id="detail", content="detail"),
        default_ratio=default_ratio,
    )


# -- the ratio store --------------------------------------------------------


class TestSplitRatioStore:
    def test_absent_ratio_returns_the_default(self) -> None:
        store = SplitRatioStore(WidgetState(), "sp")
        assert store.ratio(0.55) == 0.55

    def test_stored_ratio_survives_a_reread(self) -> None:
        state = WidgetState()
        SplitRatioStore(state, "sp").set_ratio(0.42)
        # A fresh store over the SAME scene state reads the persisted value: a
        # re-push rebuilds the arbiter but keeps the WidgetState, so the drag holds.
        assert SplitRatioStore(state, "sp").ratio(0.6) == pytest.approx(0.42)

    def test_ratio_is_clamped_into_the_guard_band(self) -> None:
        store = SplitRatioStore(WidgetState(), "sp")
        store.set_ratio(0.99)
        assert store.ratio(0.6) == 0.9  # capped
        store.set_ratio(0.01)
        assert store.ratio(0.6) == 0.1  # floored

    def test_an_out_of_band_default_is_also_clamped(self) -> None:
        # A corrupt or extreme default can never collapse a pane on first render.
        assert SplitRatioStore(WidgetState(), "sp").ratio(2.0) == 0.9

    def test_panes_are_isolated_per_scene(self) -> None:
        # Two scenes each keep their own divider; a drag in one never moves the
        # other. Per-scene isolation is the WidgetState boundary itself.
        scene_a, scene_b = WidgetState(), WidgetState()
        SplitRatioStore(scene_a, "sp").set_ratio(0.3)
        SplitRatioStore(scene_b, "sp").set_ratio(0.8)
        assert SplitRatioStore(scene_a, "sp").ratio(0.6) == pytest.approx(0.3)
        assert SplitRatioStore(scene_b, "sp").ratio(0.6) == pytest.approx(0.8)

    def test_two_panes_in_one_scene_do_not_collide(self) -> None:
        state = WidgetState()
        SplitRatioStore(state, "left").set_ratio(0.3)
        SplitRatioStore(state, "right").set_ratio(0.7)
        assert SplitRatioStore(state, "left").ratio(0.6) == pytest.approx(0.3)
        assert SplitRatioStore(state, "right").ratio(0.6) == pytest.approx(0.7)

    def test_discard_for_clears_the_ratio(self) -> None:
        # A departed scene's dragged divider must not haunt a re-added same-id pane.
        state = WidgetState()
        SplitRatioStore(state, "sp").set_ratio(0.3)
        state.discard_for("sp")
        assert SplitRatioStore(state, "sp").ratio(0.6) == 0.6  # back to the default


# -- render-order drive (spy) ----------------------------------------------


class _Recorder:
    """Shared ordered event log for the split-drive tests."""

    events: list[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.events = []
        return self


class _RecordingChildRenderer:
    """A child ``Renderer`` that logs its id when the skeleton renders it."""

    _id: str
    _rec: _Recorder

    def __new__(cls, elem: object, rec: _Recorder) -> Self:
        self = super().__new__(cls)
        self._id = cast("TextElement", elem).id
        self._rec = rec
        return self

    def begin(self) -> bool:
        self._rec.events.append(f"render:{self._id}")
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...


class _RecordingFactory:
    """A ``RendererFactory`` binding each child to a ``_RecordingChildRenderer``."""

    _rec: _Recorder

    def __new__(cls, rec: _Recorder) -> Self:
        self = super().__new__(cls)
        self._rec = rec
        return self

    def __call__(self, elem: object) -> Renderer:
        return _RecordingChildRenderer(elem, self._rec)


class _SpySplitRenderer:
    """A ``SplitPaneRenderer`` that logs each pane bracket and the divider."""

    _rec: _Recorder

    def __new__(cls, rec: _Recorder) -> Self:
        self = super().__new__(cls)
        self._rec = rec
        return self

    def begin(self) -> bool:
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...

    def open_top(self) -> None:
        self._rec.events.append("open_top")

    def close_top(self) -> None:
        self._rec.events.append("close_top")

    def draw_divider(self) -> None:
        self._rec.events.append("divider")

    def open_bottom(self) -> None:
        self._rec.events.append("open_bottom")

    def close_bottom(self) -> None:
        self._rec.events.append("close_bottom")


class _PlainRenderer:
    """A base ``Renderer`` with no split surface — not a SplitPaneRenderer."""

    def begin(self) -> bool:
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...


class TestRenderOrder:
    def test_split_brackets_top_then_divider_then_bottom(self) -> None:
        rec = _Recorder()
        split = _split()
        split.bind_renderer_factory(_RecordingFactory(rec))
        split._render_children(_SpySplitRenderer(rec))
        assert rec.events == [
            "open_top",
            "render:grid",
            "close_top",
            "divider",
            "open_bottom",
            "render:detail",
            "close_bottom",
        ]

    def test_split_requires_a_split_renderer(self) -> None:
        split = _split()
        assert isinstance(_PlainRenderer(), Renderer)
        assert not isinstance(_PlainRenderer(), SplitPaneRenderer)
        with pytest.raises(TypeError, match="SplitPaneRenderer"):
            split._render_children(_PlainRenderer())


# -- geometry relationship (fake layout) -----------------------------------


class _SplitLayout:
    """A minimal split layout: two panes stacked with a divider between them.

    Faithful to the real renderer's structure, deliberately simpler than ImGui:
    the top pane fills ``ratio`` of the usable height at the top, the divider is a
    thin band under it, and the bottom pane fills the rest. Enough to assert the
    y-ordering and non-overlap the ImGui splitter must keep.
    """

    _avail: float
    _thickness: float
    _ratio: float
    _y: float
    rects: dict[str, tuple[float, float]]

    def __new__(cls, avail: float, thickness: float, ratio: float) -> Self:
        self = super().__new__(cls)
        self._avail = avail
        self._thickness = thickness
        self._ratio = ratio
        self._y = 0.0
        self.rects = {}
        return self

    def open(self, name: str, height: float) -> None:
        """Record a pane spanning ``height`` at the running cursor and advance."""
        self.rects[name] = (self._y, self._y + height)
        self._y += height

    def open_divider(self) -> None:
        """Record the divider band at the running cursor."""
        self.open("divider", self._thickness)

    def top_height(self) -> float:
        return self._ratio * (self._avail - self._thickness)

    def bottom_height(self) -> float:
        return (self._avail - self._thickness) - self.top_height()


class _LayoutSplitRenderer:
    """A ``SplitPaneRenderer`` driving ``_SplitLayout`` — top, divider, bottom."""

    _layout: _SplitLayout

    def __new__(cls, layout: _SplitLayout) -> Self:
        self = super().__new__(cls)
        self._layout = layout
        return self

    def begin(self) -> bool:
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...

    def open_top(self) -> None:
        self._layout.open("top", self._layout.top_height())

    def close_top(self) -> None: ...

    def draw_divider(self) -> None:
        self._layout.open_divider()

    def open_bottom(self) -> None:
        self._layout.open("bottom", self._layout.bottom_height())

    def close_bottom(self) -> None: ...


class _NullChildFactory:
    """A ``RendererFactory`` whose child renderers paint nothing."""

    def __call__(self, elem: object) -> Renderer:
        _ = elem
        return _PlainRenderer()


class TestSplitGeometry:
    def test_grid_sits_above_divider_above_detail_without_overlap(self) -> None:
        layout = _SplitLayout(avail=400.0, thickness=8.0, ratio=0.6)
        split = _split(0.6)
        split.bind_renderer_factory(_NullChildFactory())
        split._render_children(_LayoutSplitRenderer(layout))

        top_lo, top_hi = layout.rects["top"]
        div_lo, div_hi = layout.rects["divider"]
        bot_lo, bot_hi = layout.rects["bottom"]
        # y-ordering: grid, then divider, then detail — each begins where the
        # previous ended, so the three bands are contiguous and disjoint.
        assert top_hi == div_lo
        assert div_hi == bot_lo
        assert top_lo < div_lo < bot_lo
        # Non-overlap and full coverage of the available height.
        assert top_lo == 0.0
        assert bot_hi == pytest.approx(400.0)
        # The default ratio gives the grid the larger share.
        assert (top_hi - top_lo) > (bot_hi - bot_lo)
