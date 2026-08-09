"""The draggable grid/detail split: ratio store, render order, and geometry.

Headless coverage for the two-pane split. The store owns the Display-local
divider ratio in per-scene ``WidgetState`` — clamped, isolated per scene, and
durable across a re-push. ``SplitPaneElement`` drives a ``SplitPaneRenderer`` in
top → divider → bottom order and rejects a plain renderer. A geometry double
proves the fixed relationship the real ImGui splitter must keep: the grid rect
sits above the divider, which sits above the detail rect, with no overlap.

Two guards close the ImGui-boundary gaps the rest of the file's Python doubles
leave open. ``TestSplitterSignature`` replays ``ImGuiSplitPaneRenderer`` itself
against the *installed* ``imgui.internal.splitter_behavior`` binding — the call
site's positional order and its 3-tuple unpack must bind to the real signature,
so a binding upgrade or a call-site edit fails a test, not the live display.
``TestFactoryDispatch`` proves a real ``ImGuiRendererFactory`` resolves the split
to its own renderer, not to the ``GroupElement`` entry it also matches. The live
drag itself is a Level-6 visual check.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Self, cast
from unittest.mock import MagicMock

import pytest
from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.split_pane import ImGuiSplitPaneRenderer
from punt_lux.display.renderers.imgui.split_ratio_store import SplitRatioStore
from punt_lux.display.replica.widget_state import WidgetState
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.split_pane import SplitPaneElement, SplitPaneRenderer
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderer import Renderer

if TYPE_CHECKING:
    from punt_lux.display.texture_cache import TextureCache

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

    def test_ratio_is_clamped_only_off_the_degenerate_edges(self) -> None:
        # The store's job is to reject 0/1 garbage, not impose layout policy; the
        # renderer's per-frame pixel floors are the real clamp. So the band is
        # degenerate: 1.0 -> 0.99, 0.0 -> 0.01, and everything strictly between is
        # left untouched.
        store = SplitRatioStore(WidgetState(), "sp")
        store.set_ratio(1.0)
        assert store.ratio(0.6) == 0.99  # capped off the top edge
        store.set_ratio(0.0)
        assert store.ratio(0.6) == 0.01  # floored off the bottom edge

    def test_pixel_floor_fraction_on_a_tall_pane_survives_unclamped(self) -> None:
        # Regression: on a tall pane the renderer's floor (a few grid rows) sits at
        # a fraction well below the old [0.1, 0.9] band, so a drag to the extreme
        # snapped back on release when the store reclamped. The degenerate band
        # must pass such a fraction through untouched, so the drag holds.
        state = WidgetState()
        floor_fraction = 0.03  # e.g. 64px of grid in a ~2000px pane
        SplitRatioStore(state, "sp").set_ratio(floor_fraction)
        assert SplitRatioStore(state, "sp").ratio(0.6) == pytest.approx(floor_fraction)
        SplitRatioStore(state, "sp").set_ratio(0.97)  # symmetric detail-floor case
        assert SplitRatioStore(state, "sp").ratio(0.6) == pytest.approx(0.97)

    def test_non_finite_is_rejected_as_garbage(self) -> None:
        # NaN/inf never come from the renderer (top+bottom > 0 is guarded), but a
        # corrupt slot or a bad caller must not poison the split: set is ignored,
        # and a corrupted stored NaN reads back as the default.
        store = SplitRatioStore(WidgetState(), "sp")
        store.set_ratio(0.4)
        store.set_ratio(math.nan)  # ignored — the good value stands
        assert store.ratio(0.6) == pytest.approx(0.4)
        store.set_ratio(math.inf)  # ignored too
        assert store.ratio(0.6) == pytest.approx(0.4)

    def test_an_out_of_band_default_is_confined(self) -> None:
        # A corrupt or extreme default can never collapse a pane on first render.
        assert SplitRatioStore(WidgetState(), "sp").ratio(2.0) == 0.99

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

    def test_a_detached_pane_renders_as_a_plain_stack_without_a_divider(self) -> None:
        # A patch removing the detail detaches a child (remove_child), leaving one
        # pane. With nothing to split, the remaining child renders through the
        # inherited plain stack — no divider, no SplitPaneRenderer required — so a
        # two-value unpack can never raise and kill the frame.
        rec = _Recorder()
        split = _split()
        split.bind_renderer_factory(_RecordingFactory(rec))
        split.remove_child(split.children[1])  # drop the detail pane
        assert len(split.children) == 1
        split._render_children(_PlainRenderer())  # a non-split renderer is accepted
        assert rec.events == ["render:grid"]  # the survivor renders, no split calls

    def test_a_fully_detached_split_renders_nothing(self) -> None:
        # Both panes gone: the stack is empty, so rendering is a no-op — never an
        # unpack error.
        rec = _Recorder()
        split = _split()
        split.bind_renderer_factory(_RecordingFactory(rec))
        split.remove_child(split.children[1])
        split.remove_child(split.children[0])
        assert split.children == ()
        split._render_children(_PlainRenderer())
        assert rec.events == []


# -- wire decode: the one-way degradation to a plain group ------------------


class TestWireDecode:
    def test_from_dict_rejects_the_server_constructed_split(self) -> None:
        # SplitPaneElement inherits GroupElement's encoder but not its __new__
        # signature, so the inherited from_dict would raise a confusing TypeError.
        # The override refuses explicitly, naming the degradation contract.
        with pytest.raises(ValueError, match="server-constructed and has no wire"):
            SplitPaneElement.from_dict(_split().to_dict())

    def test_emitted_json_decodes_as_a_plain_group(
        self, element_factory: JsonElementFactory
    ) -> None:
        # The pane emits kind="group"; the registry decodes that JSON to a plain
        # rows GroupElement — the documented one-way degradation. Production decode
        # takes this path and never touches the rejected SplitPaneElement.from_dict.
        decoded = element_factory.element_from_dict(_split().to_dict())
        assert type(decoded) is GroupElement
        assert decoded.kind == "group"
        assert decoded.layout == "rows"
        assert [child.id for child in decoded.children] == ["grid", "detail"]


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


# -- real splitter_behavior signature guard --------------------------------


def _parse_params(fn: object) -> list[tuple[str, str, bool]]:
    """Parse ``[(name, annotation, required)]`` from a nanobind doc signature.

    ``inspect.signature`` raises on nanobind bindings, so read the first doc
    line: ``splitter_behavior(bb: ...ImRect, id_: int, ..., bg_col: int = 0)``. No
    parameter annotation contains a comma (they are dotted paths), so the split on
    comma is safe up to the ``->`` return. ``required`` is False for a trailing
    optional (a param carrying a ``=`` default) — the call site need not supply it.
    """
    doc = (fn.__doc__ or "").splitlines()[0]
    inner = doc[doc.index("(") + 1 : doc.rindex(") ->")]
    params: list[tuple[str, str, bool]] = []
    for raw in inner.split(","):
        part = raw.strip()
        if not part:
            continue
        name = part.split(":")[0].split("=")[0].strip()
        annotation = part.split(":", 1)[1].split("=")[0].strip() if ":" in part else ""
        params.append((name, annotation, "=" not in part))
    return params


def _return_arity(fn: object) -> int:
    """Return the arity of a ``-> tuple[...]`` return from the doc signature."""
    doc = (fn.__doc__ or "").splitlines()[0]
    inner = doc[doc.rindex("tuple[") + len("tuple[") : doc.rindex("]")]
    return len(inner.split(","))


class _RealSignatureSplitter:
    """A ``splitter_behavior`` double validating each call against the binding.

    It requires the call to supply *exactly* the binding's required (non-default)
    positional args — so a dropped argument fails as loudly as an added one — and
    binds each to its parameter, rejecting a type mismatch: a ``float`` in the
    ``int`` ``id_`` slot, or a value whose class does not match the ``ImRect`` /
    ``Axis`` slot, the shape a reordered or drifted call site would produce. It
    returns a tuple of the binding's declared return arity, so the renderer's
    ``held, top, bottom = ...`` unpack pins that arity too.
    """

    _params: list[tuple[str, str, bool]]
    _required: int
    _arity: int
    __slots__ = ("_arity", "_params", "_required")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._params = _parse_params(imgui.internal.splitter_behavior)
        self._required = sum(1 for _, _, required in self._params if required)
        self._arity = _return_arity(imgui.internal.splitter_behavior)
        return self

    def __call__(self, *args: object) -> tuple[object, ...]:
        if len(args) != self._required:
            msg = (
                f"{len(args)} positional args, binding requires exactly "
                f"{self._required}"
            )
            raise TypeError(msg)
        for value, (name, annotation, _required) in zip(
            args, self._params, strict=False
        ):
            self._check(name, annotation, value)
        return (True, *([100.0] * (self._arity - 1)))

    @staticmethod
    def _check(name: str, annotation: str, value: object) -> None:
        if annotation == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name!r} expects int, got {type(value).__name__}")
        elif annotation == "float":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"{name!r} expects float, got {type(value).__name__}")
        elif type(value).__name__ != annotation.rsplit(".", maxsplit=1)[-1]:
            got = type(value).__name__
            raise TypeError(f"{name!r} expects {annotation}, got {got}")


class _StoreFactory:
    """A minimal factory exposing the ``widget_state`` the store is keyed on."""

    _state: WidgetState
    __slots__ = ("_state",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._state = WidgetState()
        return self

    @property
    def widget_state(self) -> WidgetState:
        return self._state


def _fake_split_imgui(splitter: _RealSignatureSplitter) -> MagicMock:
    """A fake ``imgui`` for the renderer: real geometry types, faked frame calls.

    ``ImRect``/``Axis``/``ImVec2`` are the real (context-free) constructors so the
    call passes genuine types into the splitter double; the calls that need a live
    frame (``get_id``, cursor/region, colour, draw list, ``dummy``) are stubbed.
    """
    fake = MagicMock()
    fake.get_id.return_value = 7
    fake.get_content_region_avail.return_value = imgui.ImVec2(400.0, 300.0)
    fake.get_cursor_screen_pos.return_value = imgui.ImVec2(0.0, 100.0)
    fake.get_text_line_height_with_spacing.return_value = 16.0
    # The grab colour resolves through the vec4 helpers, never the ambiguous
    # get_color_u32 int overloads.
    fake.Col_.separator.value = 28
    fake.get_style_color_vec4.return_value = imgui.ImVec4(0.5, 0.5, 0.5, 1.0)
    fake.color_convert_float4_to_u32.return_value = 0xFF808080
    fake.ImVec2 = imgui.ImVec2
    fake.internal.ImRect = imgui.internal.ImRect
    fake.internal.Axis = imgui.internal.Axis
    fake.internal.splitter_behavior = splitter
    return fake


class TestSplitterSignature:
    def test_draw_divider_binds_to_the_installed_splitter_signature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Drive the real renderer against the real binding's signature: the call
        # site's positional order and 3-tuple unpack must bind cleanly, and the
        # held drag must persist the new ratio into the store.
        splitter = _RealSignatureSplitter()
        monkeypatch.setattr(
            "punt_lux.display.renderers.imgui.split_pane.imgui",
            _fake_split_imgui(splitter),
        )
        factory = cast("ImGuiRendererFactory", _StoreFactory())
        renderer = ImGuiSplitPaneRenderer(_split(), factory)
        renderer.draw_divider()  # raises TypeError on any signature mismatch
        # held=True with top==bottom==100 → the store records the 0.5 split.
        store = SplitRatioStore(factory.widget_state, "sp")
        assert store.ratio(0.6) == pytest.approx(0.5)

    def test_the_guard_reproduces_a_drifted_call_site(self) -> None:
        # A float bound to the int ``id_`` slot — the shape a reordered call site
        # (size where the id belongs) produces — is caught, not passed to a live
        # frame.
        splitter = _RealSignatureSplitter()
        rect = imgui.internal.ImRect(0.0, 0.0, 10.0, 8.0)
        with pytest.raises(TypeError, match="id_"):
            splitter(rect, 3.0, imgui.internal.Axis.y, 100.0, 100.0, 64.0, 48.0)

    def test_the_guard_rejects_a_dropped_argument(self) -> None:
        # A call site that DROPS a required arg (six, not the seven the binding
        # requires) must fail as loudly as a reorder — not slip through.
        splitter = _RealSignatureSplitter()
        rect = imgui.internal.ImRect(0.0, 0.0, 10.0, 8.0)
        with pytest.raises(TypeError, match="requires exactly"):
            splitter(rect, 7, imgui.internal.Axis.y, 100.0, 100.0, 64.0)

    def test_the_guard_accepts_exactly_the_required_arity_and_rejects_more(
        self,
    ) -> None:
        # Exactly the seven required params (bb, id_, axis, size1, size2,
        # min_size1, min_size2) bind cleanly; an eighth positional — supplying a
        # defaulted trailing param the call site should not — is rejected too.
        splitter = _RealSignatureSplitter()
        rect = imgui.internal.ImRect(0.0, 0.0, 10.0, 8.0)
        seven = (rect, 7, imgui.internal.Axis.y, 100.0, 100.0, 64.0, 48.0)
        assert splitter(*seven) == (True, 100.0, 100.0)  # binds, returns 3-tuple
        with pytest.raises(TypeError, match="requires exactly"):
            splitter(*seven, 0.0)  # an eighth positional

    def test_the_guard_pins_the_three_tuple_return_arity(self) -> None:
        # The renderer unpacks three values; the binding must declare three.
        assert _return_arity(imgui.internal.splitter_behavior) == 3

    def test_grab_colour_avoids_the_ambiguous_int_overload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # get_color_u32 has both an index-int and a packed-u32-int overload, so a
        # bare int is ambiguous (two reviewers disagreed which wins). The grab must
        # resolve the theme colour to a vec4 and pack it — never call get_color_u32.
        fake = _fake_split_imgui(_RealSignatureSplitter())
        monkeypatch.setattr("punt_lux.display.renderers.imgui.split_pane.imgui", fake)
        factory = cast("ImGuiRendererFactory", _StoreFactory())
        ImGuiSplitPaneRenderer(_split(), factory).draw_divider()
        fake.get_color_u32.assert_not_called()
        fake.color_convert_float4_to_u32.assert_called_once_with(
            fake.get_style_color_vec4.return_value
        )


# -- factory dispatch guard -------------------------------------------------


class TestFactoryDispatch:
    def test_factory_resolves_the_split_to_its_own_renderer(self) -> None:
        # SplitPaneElement isinstance-matches both its own dispatch entry and
        # GroupElement's; a reorder would silently downgrade it to an inert
        # stacked group. A real factory must yield the split renderer.
        factory = ImGuiRendererFactory(
            widget_state=WidgetState(),
            texture_cache=cast("TextureCache", MagicMock()),
            emit=lambda _payload: None,
        )
        assert isinstance(factory(_split()), ImGuiSplitPaneRenderer)
