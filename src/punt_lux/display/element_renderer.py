# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render protocol Element dataclasses as ImGui widgets."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

import numpy as np

from punt_lux.display.renderers import (
    ButtonRenderer,
    CheckboxRenderer,
    ColorPickerRenderer,
    ComboRenderer,
    ImageRenderer,
    InputNumberRenderer,
    InputTextRenderer,
    MarkdownRenderer,
    ProgressRenderer,
    RadioRenderer,
    SelectableRenderer,
    SeparatorRenderer,
    SliderRenderer,
    SpinnerRenderer,
    TextRenderer,
)
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol import (
    CollapsingHeaderElement,
    GroupElement,
    RemoteEventHandlerInvocation,
    TabBarElement,
    WindowElement,
)
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.draw_command_kind import DrawCommand
from punt_lux.protocol.elements.draw_commands_curve import BezierCubic
from punt_lux.protocol.elements.draw_commands_line import Line, Polyline
from punt_lux.protocol.elements.draw_commands_shape import (
    Circle,
    Rect,
    Triangle,
)
from punt_lux.protocol.elements.draw_commands_text import TextGlyph
from punt_lux.protocol.elements.graphics import DrawElement
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.spinner import SpinnerElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.scene import WidgetState

if TYPE_CHECKING:
    from punt_lux.protocol import Element
    from punt_lux.types import EmitEventFn

logger = logging.getLogger(__name__)

# Callback type for checking/clearing dirty window state owned by SceneManager.
type DirtyWindowFn = Callable[[str], bool]


class ElementRenderer:
    """Render protocol Element dataclasses as ImGui widgets."""

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _table_renderer: TableRenderer
    _emit_event: EmitEventFn
    _current_scene_id: str | None
    _check_dirty_window: DirtyWindowFn
    # Per-kind renderer classes for the basics + inputs families.
    # Other families still go through ``_RENDERERS`` until extracted.
    _text_renderer: TextRenderer
    _image_renderer: ImageRenderer
    _separator_renderer: SeparatorRenderer
    _progress_renderer: ProgressRenderer
    _spinner_renderer: SpinnerRenderer
    _markdown_renderer: MarkdownRenderer
    _button_renderer: ButtonRenderer
    _slider_renderer: SliderRenderer
    _checkbox_renderer: CheckboxRenderer
    _combo_renderer: ComboRenderer
    _input_text_renderer: InputTextRenderer
    _input_number_renderer: InputNumberRenderer
    _radio_renderer: RadioRenderer
    _color_picker_renderer: ColorPickerRenderer
    _selectable_renderer: SelectableRenderer

    _RENDERERS: ClassVar[dict[str, str]] = {
        "draw": "_render_draw",
        "group": "_render_group",
        "tab_bar": "_render_tab_bar",
        "collapsing_header": "_render_collapsing_header",
        "window": "_render_window",
        "tree": "_render_tree",
        "table": "_render_table",
        "plot": "_render_plot",
        "modal": "_render_modal",
        "dialog": "_render_dialog",
    }

    def __new__(
        cls,
        widget_state: WidgetState,
        texture_cache: TextureCache,
        table_renderer: TableRenderer,
        emit_event: EmitEventFn,
        check_dirty_window: DirtyWindowFn,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._texture_cache = texture_cache
        self._table_renderer = table_renderer
        self._emit_event = emit_event
        self._check_dirty_window = check_dirty_window
        self._current_scene_id = None
        self._text_renderer = TextRenderer()
        self._image_renderer = ImageRenderer(texture_cache)
        self._separator_renderer = SeparatorRenderer()
        self._progress_renderer = ProgressRenderer()
        self._spinner_renderer = SpinnerRenderer()
        self._markdown_renderer = MarkdownRenderer()
        self._button_renderer = ButtonRenderer()
        self._slider_renderer = SliderRenderer(widget_state, emit_event)
        self._checkbox_renderer = CheckboxRenderer(widget_state, emit_event)
        self._combo_renderer = ComboRenderer(widget_state, emit_event)
        self._input_text_renderer = InputTextRenderer(widget_state, emit_event)
        self._input_number_renderer = InputNumberRenderer(widget_state, emit_event)
        self._radio_renderer = RadioRenderer(widget_state, emit_event)
        self._color_picker_renderer = ColorPickerRenderer(widget_state, emit_event)
        self._selectable_renderer = SelectableRenderer(widget_state, emit_event)
        return self

    # Per-kind dispatch table: (element type, renderer-attribute name).  Single
    # source of truth for both _dispatch_native and element_kind_count — adding
    # a per-kind renderer here updates both call sites at once.
    _NATIVE_DISPATCH: ClassVar[tuple[tuple[type, str], ...]] = (
        (TextElement, "_text_renderer"),
        (ImageElement, "_image_renderer"),
        (SeparatorElement, "_separator_renderer"),
        (ProgressElement, "_progress_renderer"),
        (SpinnerElement, "_spinner_renderer"),
        (MarkdownElement, "_markdown_renderer"),
        (ButtonElement, "_button_renderer"),
        (SliderElement, "_slider_renderer"),
        (CheckboxElement, "_checkbox_renderer"),
        (ComboElement, "_combo_renderer"),
        (InputTextElement, "_input_text_renderer"),
        (InputNumberElement, "_input_number_renderer"),
        (RadioElement, "_radio_renderer"),
        (ColorPickerElement, "_color_picker_renderer"),
        (SelectableElement, "_selectable_renderer"),
    )

    # Renderer attributes that own per-scene WidgetState.  The widget_state
    # setter forwards updates to each so a scene switch reaches every input
    # renderer's view of widget state simultaneously.
    _WIDGET_STATE_RENDERERS: ClassVar[tuple[str, ...]] = (
        "_slider_renderer",
        "_checkbox_renderer",
        "_combo_renderer",
        "_input_text_renderer",
        "_input_number_renderer",
        "_radio_renderer",
        "_color_picker_renderer",
        "_selectable_renderer",
    )

    @property
    def element_kind_count(self) -> int:
        """Return the number of supported element kinds."""
        return len(self._RENDERERS) + len(self._NATIVE_DISPATCH)

    @property
    def widget_state(self) -> WidgetState:
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        self._widget_state = value
        for attr in self._WIDGET_STATE_RENDERERS:
            getattr(self, attr).widget_state = value

    @property
    def current_scene_id(self) -> str | None:
        return self._current_scene_id

    @current_scene_id.setter
    def current_scene_id(self, value: str | None) -> None:
        self._current_scene_id = value

    # -- dispatch --------------------------------------------------------------

    def render_element(self, elem: Element) -> None:
        """Dispatch an element to its kind-specific renderer."""
        from imgui_bundle import imgui

        handled_natively = self._dispatch_native(elem)
        if not handled_natively:
            method_name = self._RENDERERS.get(elem.kind)
            if method_name is not None:
                getattr(self, method_name)(elem)
            else:
                imgui.text(f"[unsupported element: {elem.kind}]")

        # Unstyled text with tooltip uses selectable() in TextRenderer
        # and handles its own tooltip there.  All other elements (including
        # styled text) use this generic tooltip handler.
        is_text_with_inline_tooltip = (
            elem.kind == "text"
            and not getattr(elem, "style", None)
            and getattr(elem, "tooltip", None)
        )
        if not is_text_with_inline_tooltip:
            tooltip = getattr(elem, "tooltip", None)
            if tooltip and imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value):
                imgui.set_tooltip(tooltip)

    def _dispatch_native(self, elem: Element) -> bool:
        """Route per-kind renderer classes (basics + inputs).

        Returns True iff the element belongs to a family with a per-kind
        renderer class.
        """
        for element_type, renderer_attr in self._NATIVE_DISPATCH:
            if isinstance(elem, element_type):
                getattr(self, renderer_attr).render(elem)
                return True
        return False

    # -- color helpers ---------------------------------------------------------

    @staticmethod
    def _parse_color(
        color: str | list[int] | tuple[int, ...] | Any,
    ) -> tuple[int, int, int, int]:
        """Parse a color value to (r, g, b, a) ints 0-255."""
        if isinstance(color, (list, tuple)):
            try:
                if len(color) >= 4:
                    return (
                        int(color[0]),
                        int(color[1]),
                        int(color[2]),
                        int(color[3]),
                    )
                if len(color) == 3:
                    return (
                        int(color[0]),
                        int(color[1]),
                        int(color[2]),
                        255,
                    )
            except (TypeError, ValueError):
                pass
            logger.warning("Invalid RGBA color %r; using fallback white", color)
            return (255, 255, 255, 255)
        if not isinstance(color, str):
            logger.warning(
                "Invalid color type %r; using fallback white",
                type(color),
            )
            return (255, 255, 255, 255)
        h = color.lstrip("#")
        try:
            if len(h) == 6:
                r, g, b = (
                    int(h[0:2], 16),
                    int(h[2:4], 16),
                    int(h[4:6], 16),
                )
                return (r, g, b, 255)
            if len(h) == 8:
                r, g, b, a = (
                    int(h[0:2], 16),
                    int(h[2:4], 16),
                    int(h[4:6], 16),
                    int(h[6:8], 16),
                )
                return (r, g, b, a)
        except ValueError:
            logger.warning("Invalid hex color %r; using fallback white", color)
        return (255, 255, 255, 255)

    @staticmethod
    def _to_imgui_color(
        color: str | list[int] | tuple[int, ...] | Any,
    ) -> int:
        """Convert a color value to ImGui packed color (ImU32)."""
        from imgui_bundle import ImVec4, imgui

        r, g, b, a = ElementRenderer._parse_color(color)
        result: int = imgui.get_color_u32(
            ImVec4(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        )
        return result

    # -- container rendering ---------------------------------------------------

    def _render_group(self, elem: Element) -> None:
        from imgui_bundle import imgui

        grp = cast("GroupElement", elem)
        layout = grp.layout

        if layout == "paged":
            self._render_paged_group(grp)
            return

        for i, child in enumerate(grp.children):
            if layout == "columns" and i > 0:
                imgui.same_line()
            self.render_element(child)

    def _paged_group_state_key(self, grp_id: str, page_source: str | None) -> str:
        """Return the widget_state key for a paged group's page index."""
        return page_source if page_source else f"{grp_id}__pg_idx"

    def _paged_group_read_index(self, state_key: str, total: int) -> int:
        """Read and clamp the current page index from widget_state."""
        raw = self._widget_state.get(state_key)
        page_idx = raw if isinstance(raw, int) else 0
        return max(0, min(page_idx, total - 1)) if total else 0

    def _render_paged_group(self, grp: Any) -> None:
        """Render a paged group with built-in Prev/Next navigation."""
        from imgui_bundle import imgui

        pages = grp.pages
        total = len(pages) if pages else 0
        page_source: str | None = grp.page_source
        state_key = self._paged_group_state_key(grp.id, page_source)
        page_idx = self._paged_group_read_index(state_key, total)

        # Nav row: << Prev | [combo] | Next >>
        if imgui.button(f"<< Prev##{grp.id}_prev") and page_idx > 0:
            page_idx -= 1
            self._widget_state.set(state_key, page_idx)
        imgui.same_line()

        # Render the combo (from page_source) inline; other children after.
        other_children: list[Any] = []
        for child in grp.children:
            if page_source and getattr(child, "id", None) == page_source:
                self.render_element(child)
                imgui.same_line()
            else:
                other_children.append(child)

        if imgui.button(f"Next >>##{grp.id}_next") and page_idx < total - 1:
            page_idx += 1
            self._widget_state.set(state_key, page_idx)

        # Re-read after all interactions (Prev, combo change, Next) so the
        # page content always reflects the final widget_state value.
        page_idx = self._paged_group_read_index(state_key, total)

        for child in other_children:
            self.render_element(child)

        if pages and 0 <= page_idx < total:
            for child in pages[page_idx]:
                self.render_element(child)

    def _render_tab_bar(self, elem: Element) -> None:
        from imgui_bundle import imgui

        tb = cast("TabBarElement", elem)
        if imgui.begin_tab_bar(f"##{tb.id}"):
            for tab in tb.tabs:
                tab_label: str = tab.get("label", "Tab")
                if imgui.begin_tab_item(tab_label)[0]:
                    for child in tab.get("children", []):
                        self.render_element(child)
                    imgui.end_tab_item()
            imgui.end_tab_bar()

    def _render_collapsing_header(self, elem: Element) -> None:
        from imgui_bundle import imgui

        ch = cast("CollapsingHeaderElement", elem)
        flags = imgui.TreeNodeFlags_.default_open.value if ch.default_open else 0
        if imgui.collapsing_header(f"{ch.label}##{ch.id}", flags=flags):
            for child in ch.children:
                self.render_element(child)

    def _render_window(self, elem: Element) -> None:
        from imgui_bundle import imgui

        win = cast("WindowElement", elem)
        flags = 0
        if win.no_move:
            flags |= imgui.WindowFlags_.no_move.value
        if win.no_resize:
            flags |= imgui.WindowFlags_.no_resize.value
        if win.no_collapse:
            flags |= imgui.WindowFlags_.no_collapse.value
        if win.no_title_bar:
            flags |= imgui.WindowFlags_.no_title_bar.value
        if win.no_scrollbar:
            flags |= imgui.WindowFlags_.no_scrollbar.value
        if win.auto_resize:
            flags |= imgui.WindowFlags_.always_auto_resize.value

        # check_dirty_window returns True and clears the flag when
        # the window was marked dirty by a scene update.
        if self._check_dirty_window(win.id):
            cond = imgui.Cond_.always.value
        else:
            cond = imgui.Cond_.first_use_ever.value
        imgui.set_next_window_pos((win.x, win.y), cond)
        imgui.set_next_window_size((win.width, win.height), cond)

        title = win.title or win.id
        expanded, _ = imgui.begin(f"{title}##{win.id}", flags=flags)
        if expanded:
            for child in win.children:
                self.render_element(child)
        imgui.end()

    # -- tree rendering --------------------------------------------------------

    def _render_tree(self, elem: Element) -> None:
        from imgui_bundle import imgui

        tree: Any = elem
        eid: str = tree.id
        label: str = tree.label
        nodes: list[dict[str, Any]] = tree.nodes

        flat: bool = getattr(tree, "flat", False)

        if label:
            imgui.text(label)
        for i, node in enumerate(nodes):
            self._render_tree_node(node, f"{eid}_{i}", eid, flat=flat)

    def _render_tree_node(
        self,
        node: dict[str, Any],
        node_id: str,
        tree_id: str,
        *,
        flat: bool = False,
    ) -> None:
        from imgui_bundle import imgui

        label: str = node.get("label", "")
        children: list[dict[str, Any]] = node.get("children", [])

        if children:
            if flat:
                no_push = imgui.TreeNodeFlags_.no_tree_push_on_open.value
                opened = imgui.tree_node_ex(f"{label}##{node_id}", no_push)
            else:
                opened = imgui.tree_node(f"{label}##{node_id}")
            if imgui.is_item_clicked():
                self._emit_node_click(tree_id, node_id, label)
            if opened:
                for i, child in enumerate(children):
                    self._render_tree_node(child, f"{node_id}_{i}", tree_id, flat=flat)
                if not flat:
                    imgui.tree_pop()
        else:
            if flat:
                selected = False
                clicked, _ = imgui.selectable(f"{label}##{node_id}", selected)
                if clicked:
                    self._emit_node_click(tree_id, node_id, label)
            else:
                leaf = imgui.TreeNodeFlags_.leaf.value
                no_push = imgui.TreeNodeFlags_.no_tree_push_on_open.value
                flags = leaf | no_push
                imgui.tree_node_ex(f"{label}##{node_id}", flags)
                if imgui.is_item_clicked():
                    self._emit_node_click(tree_id, node_id, label)

    def _emit_node_click(self, tree_id: str, node_id: str, label: str) -> None:
        self._emit_event(
            RemoteEventHandlerInvocation(
                element_id=tree_id,
                action="node_clicked",
                ts=time.time(),
                value={"node_id": node_id, "label": label},
            )
        )

    # -- table rendering -------------------------------------------------------

    def _render_table(self, elem: Element) -> None:
        """Delegate table rendering to the extracted TableRenderer."""
        from punt_lux.protocol import TableElement

        table = cast("TableElement", elem)
        scene_id = self._current_scene_id or ""
        self._table_renderer.render(table, scene_id)

    # -- plot rendering --------------------------------------------------------

    def _render_plot(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, implot

        plt: Any = elem
        eid: str = plt.id
        title: str = plt.title
        plot_title = title if "##" in title else f"{title}##{eid}"

        if implot.begin_plot(plot_title, ImVec2(plt.width, plt.height)):
            if plt.x_label or plt.y_label:
                implot.setup_axes(plt.x_label or "", plt.y_label or "")

            for series in plt.series:
                s_label: str = series.get("label", "data")
                s_type: str = series.get("type", "line")
                x_data = np.array(series.get("x", []), dtype=np.float64)
                y_data = np.array(series.get("y", []), dtype=np.float64)

                if len(x_data) == 0 or len(y_data) == 0:
                    continue

                if s_type == "line":
                    implot.plot_line(s_label, x_data, y_data)
                elif s_type == "scatter":
                    implot.plot_scatter(s_label, x_data, y_data)
                elif s_type == "bar":
                    try:
                        implot.plot_bars(s_label, x_data, y_data, 0.67)
                    except TypeError:
                        implot.plot_bars(s_label, y_data, 0.67)

            implot.end_plot()

    # -- modal rendering -------------------------------------------------------

    _MODAL_OPEN = 1
    _MODAL_CLOSED = 0

    def _render_modal(self, elem: Element) -> None:
        from imgui_bundle import imgui

        md: Any = elem
        eid: str = md.id
        title: str = md.title or md.id
        should_open: bool = md.open
        popup_id = f"{title}##{eid}"
        open_key = f"{eid}__open"
        dismiss_key = f"{eid}__dismissed"

        on = self._MODAL_OPEN
        off = self._MODAL_CLOSED
        was_open = self._widget_state.ensure(open_key, off) == on
        dismissed = self._widget_state.ensure(dismiss_key, off) == on

        # When the agent sets open=False, clear the dismissed latch
        # so the modal can be re-opened later.
        if not should_open:
            if was_open or dismissed:
                self._widget_state.set(open_key, self._MODAL_CLOSED)
                self._widget_state.set(dismiss_key, self._MODAL_CLOSED)
            return

        # Don't re-open if user already dismissed and agent hasn't acked yet.
        if should_open and not was_open and not dismissed:
            imgui.open_popup(popup_id)
            self._widget_state.set(open_key, self._MODAL_OPEN)
            was_open = True

        visible, _p_open = imgui.begin_popup_modal(popup_id, True)  # noqa: FBT003

        if visible:
            for child in md.children:
                self.render_element(child)
            imgui.end_popup()

        if was_open and not visible:
            self._widget_state.set(open_key, self._MODAL_CLOSED)
            self._widget_state.set(dismiss_key, self._MODAL_OPEN)
            self._emit_event(
                RemoteEventHandlerInvocation(
                    element_id=eid,
                    action="closed",
                    ts=time.time(),
                    value=None,
                )
            )

    # -- dialog rendering ------------------------------------------------------

    def _render_dialog(self, elem: Element) -> None:
        """Paint a DialogElement frame and recurse into its child Buttons."""
        import logging

        _dlog = logging.getLogger("lux.render.dialog")
        from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
        from punt_lux.protocol.elements.dialog import DialogElement

        _dlog.warning(
            "_render_dialog called for %s type=%s",
            elem.id,
            type(elem).__name__,
        )
        if not isinstance(elem, DialogElement):
            _dlog.warning("NOT a DialogElement — falling through as unsupported")
            msg = f"_render_dialog expected DialogElement; got {type(elem).__name__}"
            raise TypeError(msg)
        _dlog.warning(
            "DialogElement confirmed, visible=%s children=%d",
            elem.visible,
            len(elem.children),
        )
        ImGuiDialogRenderer(elem, self._widget_state, self._button_renderer).render()

    # -- draw element rendering ------------------------------------------------

    def _render_draw(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, imgui

        if not isinstance(elem, DrawElement):
            msg = f"_render_draw expected DrawElement; got {type(elem).__name__}"
            raise TypeError(msg)

        canvas_pos = imgui.get_cursor_screen_pos()
        canvas_min = ImVec2(canvas_pos.x, canvas_pos.y)
        canvas_max = ImVec2(canvas_pos.x + elem.width, canvas_pos.y + elem.height)
        draw_list = imgui.get_window_draw_list()

        draw_list.push_clip_rect(canvas_min, canvas_max, True)  # noqa: FBT003

        if elem.bg_color is not None:
            bg_u32 = self._to_imgui_color(elem.bg_color)
            draw_list.add_rect_filled(canvas_min, canvas_max, bg_u32)

        ox, oy = canvas_pos.x, canvas_pos.y
        # Wire decoding ran in DrawCommandDecoder; the renderer cannot
        # receive a malformed command. The previous try/except that swallowed
        # KeyError/IndexError/TypeError/ValueError was masking the silent-
        # default bug the typed decoder now prevents at the wire boundary.
        for cmd in elem.commands:
            self._dispatch_draw_cmd(draw_list, cmd, ox, oy)

        draw_list.pop_clip_rect()
        imgui.dummy(ImVec2(elem.width, elem.height))
        _ = elem.id  # used for future interaction tracking

    def _dispatch_draw_cmd(
        self,
        draw_list: Any,
        cmd: DrawCommand,
        ox: float,
        oy: float,
    ) -> None:
        match cmd:
            case Line():
                self._draw_line(draw_list, cmd, ox, oy)
            case Rect():
                self._draw_rect(draw_list, cmd, ox, oy)
            case Circle():
                self._draw_circle(draw_list, cmd, ox, oy)
            case Triangle():
                self._draw_triangle(draw_list, cmd, ox, oy)
            case TextGlyph():
                self._draw_text(draw_list, cmd, ox, oy)
            case Polyline():
                self._draw_polyline(draw_list, cmd, ox, oy)
            case BezierCubic():
                self._draw_bezier(draw_list, cmd, ox, oy)
            case _:
                # Unreachable in normal use — DrawCommand is the closed union
                # of the typed records registered with the decoder. Raise so a
                # new kind added without renderer support fails loud rather
                # than silently rendering nothing.
                msg = f"unhandled draw command kind: {type(cmd).__name__}"
                raise TypeError(msg)

    def _draw_line(self, dl: Any, cmd: Line, ox: float, oy: float) -> None:
        from imgui_bundle import ImVec2

        color = self._to_imgui_color(cmd.color.value)
        dl.add_line(
            ImVec2(ox + cmd.p1.x, oy + cmd.p1.y),
            ImVec2(ox + cmd.p2.x, oy + cmd.p2.y),
            color,
            cmd.thickness.value,
        )

    def _draw_rect(self, dl: Any, cmd: Rect, ox: float, oy: float) -> None:
        from imgui_bundle import ImVec2

        color = self._to_imgui_color(cmd.color.value)
        if cmd.filled:
            dl.add_rect_filled(
                ImVec2(ox + cmd.min.x, oy + cmd.min.y),
                ImVec2(ox + cmd.max.x, oy + cmd.max.y),
                color,
                cmd.rounding.value,
            )
        else:
            dl.add_rect(
                ImVec2(ox + cmd.min.x, oy + cmd.min.y),
                ImVec2(ox + cmd.max.x, oy + cmd.max.y),
                color,
                cmd.rounding.value,
                0,
                cmd.thickness.value,
            )

    def _draw_circle(self, dl: Any, cmd: Circle, ox: float, oy: float) -> None:
        from imgui_bundle import ImVec2

        color = self._to_imgui_color(cmd.color.value)
        center = ImVec2(ox + cmd.center.x, oy + cmd.center.y)
        if cmd.filled:
            dl.add_circle_filled(center, cmd.radius.value, color)
        else:
            dl.add_circle(center, cmd.radius.value, color, 0, cmd.thickness.value)

    def _draw_triangle(self, dl: Any, cmd: Triangle, ox: float, oy: float) -> None:
        from imgui_bundle import ImVec2

        color = self._to_imgui_color(cmd.color.value)
        p1 = ImVec2(ox + cmd.p1.x, oy + cmd.p1.y)
        p2 = ImVec2(ox + cmd.p2.x, oy + cmd.p2.y)
        p3 = ImVec2(ox + cmd.p3.x, oy + cmd.p3.y)
        if cmd.filled:
            dl.add_triangle_filled(p1, p2, p3, color)
        else:
            dl.add_triangle(p1, p2, p3, color, cmd.thickness.value)

    def _draw_text(self, dl: Any, cmd: TextGlyph, ox: float, oy: float) -> None:
        from imgui_bundle import ImVec2

        color = self._to_imgui_color(cmd.color.value)
        dl.add_text(ImVec2(ox + cmd.pos.x, oy + cmd.pos.y), color, cmd.text)

    def _draw_polyline(self, dl: Any, cmd: Polyline, ox: float, oy: float) -> None:
        from imgui_bundle import ImVec2

        im_draw_flags_closed = 1
        color = self._to_imgui_color(cmd.color.value)
        points = [ImVec2(ox + p.x, oy + p.y) for p in cmd.points]
        flags = im_draw_flags_closed if cmd.closed else 0
        dl.add_polyline(points, color, flags, cmd.thickness.value)

    def _draw_bezier(self, dl: Any, cmd: BezierCubic, ox: float, oy: float) -> None:
        from imgui_bundle import ImVec2

        color = self._to_imgui_color(cmd.color.value)
        dl.add_bezier_cubic(
            ImVec2(ox + cmd.p1.x, oy + cmd.p1.y),
            ImVec2(ox + cmd.p2.x, oy + cmd.p2.y),
            ImVec2(ox + cmd.p3.x, oy + cmd.p3.y),
            ImVec2(ox + cmd.p4.x, oy + cmd.p4.y),
            color,
            cmd.thickness.value,
        )
