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
from punt_lux.display.renderers.draw_element_renderer import DrawElementRenderer
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
from punt_lux.protocol.elements.dialog import DialogElement
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
    from punt_lux.display.renderers.imgui import ImGuiRendererFactory
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
    # Bound after construction (the factory needs this ElementRenderer first).
    # Used only by ``_render_dialog`` to build the dialog's ImGui renderer for
    # a dialog held by a legacy container; a top-level dialog paints through
    # the ABC ``render()`` template and never reaches that method.
    _imgui_renderer_factory: ImGuiRendererFactory
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
    _draw_element_renderer: DrawElementRenderer

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
        self._checkbox_renderer = CheckboxRenderer(widget_state)
        self._combo_renderer = ComboRenderer(widget_state, emit_event)
        self._input_text_renderer = InputTextRenderer(widget_state, emit_event)
        self._input_number_renderer = InputNumberRenderer(widget_state, emit_event)
        self._radio_renderer = RadioRenderer(widget_state, emit_event)
        self._color_picker_renderer = ColorPickerRenderer(widget_state, emit_event)
        self._selectable_renderer = SelectableRenderer(widget_state, emit_event)
        self._draw_element_renderer = DrawElementRenderer()
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
    def text_renderer(self) -> TextRenderer:
        """Return the per-kind text renderer for the ImGui text adapter.

        A narrow seam: the ImGui ``ImGuiTextRenderer`` paints through this
        instance so the shared ``apply_tooltip`` pass runs against the same
        renderer the legacy dispatch used.
        """
        return self._text_renderer

    @property
    def button_renderer(self) -> ButtonRenderer:
        """Return the per-kind button renderer for the ImGui button adapter.

        The instance is owned here, not by the factory, so the D21 fire
        path and handler wrapping stay on the one renderer the migration
        exercises.
        """
        return self._button_renderer

    @property
    def checkbox_renderer(self) -> CheckboxRenderer:
        """Return the per-kind checkbox renderer for the ImGui checkbox adapter.

        This is the instance the ``widget_state`` setter re-threads per
        scene, so painting through it reads the current scene's state — not
        the factory's stale construction-time copy.
        """
        return self._checkbox_renderer

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

    @property
    def imgui_renderer_factory(self) -> ImGuiRendererFactory:
        """Return the ImGui factory bound after construction."""
        return self._imgui_renderer_factory

    @imgui_renderer_factory.setter
    def imgui_renderer_factory(self, value: ImGuiRendererFactory) -> None:
        self._imgui_renderer_factory = value

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

        self.apply_tooltip(elem)

    def apply_tooltip(self, elem: Element) -> None:
        """Paint ``elem``'s generic hover tooltip, if it has one.

        Shared post-processing for the legacy dispatch and the per-kind
        ImGui adapters. Unstyled text with a tooltip is skipped: its
        ``TextRenderer`` paints it with ``selectable()`` and emits the
        tooltip inline, so a second pass here would double it.
        """
        from imgui_bundle import imgui

        is_text_with_inline_tooltip = (
            elem.kind == "text"
            and not getattr(elem, "style", None)
            and getattr(elem, "tooltip", None)
        )
        if is_text_with_inline_tooltip:
            return
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

        other_children = self._render_paged_inline_children(grp)

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

    def _render_paged_inline_children(self, grp: Any) -> list[Any]:
        """Render the page-source combo inline; return the remaining children."""
        from imgui_bundle import imgui

        page_source: str | None = grp.page_source
        other_children: list[Any] = []
        for child in grp.children:
            if page_source and getattr(child, "id", None) == page_source:
                self.render_element(child)
                imgui.same_line()
            else:
                other_children.append(child)
        return other_children

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
        title: str = plt.title
        plot_title = title if "##" in title else f"{title}##{plt.id}"

        if implot.begin_plot(plot_title, ImVec2(plt.width, plt.height)):
            if plt.x_label or plt.y_label:
                implot.setup_axes(plt.x_label or "", plt.y_label or "")
            for series in plt.series:
                self._plot_series(series)
            implot.end_plot()

    @staticmethod
    def _plot_series(series: dict[str, Any]) -> None:
        """Plot one series (line / scatter / bar) from its wire mapping."""
        from imgui_bundle import implot

        x_data = np.array(series.get("x", []), dtype=np.float64)
        y_data = np.array(series.get("y", []), dtype=np.float64)
        if len(x_data) == 0 or len(y_data) == 0:
            return

        label: str = series.get("label", "data")
        s_type: str = series.get("type", "line")
        if s_type == "line":
            implot.plot_line(label, x_data, y_data)
        elif s_type == "scatter":
            implot.plot_scatter(label, x_data, y_data)
        elif s_type == "bar":
            try:
                implot.plot_bars(label, x_data, y_data, 0.67)
            except TypeError:
                implot.plot_bars(label, y_data, 0.67)

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
        """Paint a DialogElement held by a legacy container.

        A top-level dialog paints through the ABC ``render()`` template; one
        nested in a legacy container reaches here via ``render_element``. Drive
        the same begin/paint/end dialog renderer and recurse its child Buttons
        through the legacy per-kind dispatch so they paint via the shared
        ButtonRenderer — identical pixels to the top-level path.
        """
        if not isinstance(elem, DialogElement):
            msg = f"_render_dialog expected DialogElement; got {type(elem).__name__}"
            raise TypeError(msg)
        renderer = self._imgui_renderer_factory(elem)
        opened = renderer.begin()
        if opened:
            renderer.paint()
            # Dialog children are ABC Buttons; the legacy dispatch is typed
            # for the wire-kind union, of which ButtonElement is a member.
            for child in elem.children:
                self.render_element(cast("Element", child))
        renderer.end(opened=opened)

    # -- draw element rendering ------------------------------------------------

    def _render_draw(self, elem: Element) -> None:
        """Delegate a DrawElement to the extracted ``DrawElementRenderer``."""
        if not isinstance(elem, DrawElement):
            msg = f"_render_draw expected DrawElement; got {type(elem).__name__}"
            raise TypeError(msg)
        self._draw_element_renderer.render(elem)
