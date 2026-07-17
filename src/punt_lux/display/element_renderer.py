# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render protocol Element dataclasses as ImGui widgets."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar, Self, cast

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
from punt_lux.display.renderers.container_renderer import ContainerRenderer
from punt_lux.display.renderers.draw_element_renderer import DrawElementRenderer
from punt_lux.display.renderers.modal_renderer import ModalRenderer
from punt_lux.display.renderers.plot_renderer import PlotRenderer
from punt_lux.display.renderers.tree_renderer import TreeRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
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
    from punt_lux.protocol.elements.layout import ModalElement, TreeElement
    from punt_lux.protocol.elements.plot_element import PlotElement
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
    # Bound post-construction; only ``_render_dialog`` uses it (legacy-nested dialog).
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
    # Layout containers (group, tab bar, collapsing header, window) recurse
    # their children back through ``render_element`` via a callback.
    _container_renderer: ContainerRenderer
    # Legacy composite/leaf paint surfaces extracted into their own renderers.
    _tree_renderer: TreeRenderer
    _plot_renderer: PlotRenderer
    _modal_renderer: ModalRenderer

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
        self._slider_renderer = SliderRenderer(widget_state)
        self._checkbox_renderer = CheckboxRenderer()
        self._combo_renderer = ComboRenderer()
        self._input_text_renderer = InputTextRenderer(widget_state)
        self._input_number_renderer = InputNumberRenderer(widget_state)
        self._radio_renderer = RadioRenderer()
        self._color_picker_renderer = ColorPickerRenderer(widget_state)
        self._selectable_renderer = SelectableRenderer()
        self._draw_element_renderer = DrawElementRenderer()
        self._container_renderer = ContainerRenderer(
            widget_state, check_dirty_window, self.render_element
        )
        self._tree_renderer = TreeRenderer(emit_event)
        self._plot_renderer = PlotRenderer()
        self._modal_renderer = ModalRenderer(
            widget_state, emit_event, self.render_element
        )
        return self

    # (element type, renderer attr) — single source for _dispatch_native and count.
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

    # Renderer attrs owning per-scene WidgetState; the setter forwards scene switches.
    _WIDGET_STATE_RENDERERS: ClassVar[tuple[str, ...]] = (
        "_slider_renderer",
        "_input_text_renderer",
        "_input_number_renderer",
        "_color_picker_renderer",
        "_container_renderer",
        "_modal_renderer",
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
        """Return the per-kind checkbox renderer for the ImGui checkbox adapter."""
        return self._checkbox_renderer

    @property
    def combo_renderer(self) -> ComboRenderer:
        """Return the per-kind combo renderer for the ImGui combo adapter."""
        return self._combo_renderer

    @property
    def radio_renderer(self) -> RadioRenderer:
        """Return the per-kind radio renderer for the ImGui radio adapter."""
        return self._radio_renderer

    @property
    def selectable_renderer(self) -> SelectableRenderer:
        """Return the per-kind selectable renderer for the ImGui adapter."""
        return self._selectable_renderer

    @property
    def input_text_renderer(self) -> InputTextRenderer:
        """Return the per-kind input_text renderer for the ImGui adapter."""
        return self._input_text_renderer

    @property
    def slider_renderer(self) -> SliderRenderer:
        """Return the per-kind slider renderer for the ImGui adapter.

        Each interactive input renderer (slider, color_picker, input_number) is
        owned here, not by the factory, so the D21 fire path and the commit-echo
        reconciliation stay on the one renderer the ABC adapter paints through.
        """
        return self._slider_renderer

    @property
    def color_picker_renderer(self) -> ColorPickerRenderer:
        """Return the color-picker renderer (owned here — see ``slider_renderer``)."""
        return self._color_picker_renderer

    @property
    def input_number_renderer(self) -> InputNumberRenderer:
        """Return the input_number renderer (owned here — see ``slider_renderer``)."""
        return self._input_number_renderer

    @property
    def widget_state(self) -> WidgetState:
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        self._widget_state = value
        for attr in self._WIDGET_STATE_RENDERERS:
            getattr(self, attr).widget_state = value
        # The ABC tab-bar adapter reads echo-suppression state through the
        # factory; re-thread it so a scene switch reaches the ABC path too.
        self._imgui_renderer_factory.widget_state = value

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

        # Dialog paints its own tooltip in ImGuiDialogRenderer.end; skip generic pass.
        if not isinstance(elem, DialogElement):
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
        """Delegate group rendering to the ContainerRenderer."""
        self._container_renderer.render_group(elem)

    def _render_tab_bar(self, elem: Element) -> None:
        """Delegate tab-bar rendering to the ContainerRenderer."""
        self._container_renderer.render_tab_bar(elem)

    def _render_collapsing_header(self, elem: Element) -> None:
        """Delegate collapsing-header rendering to the ContainerRenderer."""
        self._container_renderer.render_collapsing_header(elem)

    def _render_window(self, elem: Element) -> None:
        """Delegate window rendering to the ContainerRenderer."""
        self._container_renderer.render_window(elem)

    # -- tree rendering --------------------------------------------------------

    def _render_tree(self, elem: Element) -> None:
        """Delegate tree rendering to the extracted TreeRenderer."""
        self._tree_renderer.render(cast("TreeElement", elem))

    # -- table rendering -------------------------------------------------------

    def _render_table(self, elem: Element) -> None:
        """Delegate table rendering to the extracted TableRenderer."""
        from punt_lux.protocol import TableElement

        table = cast("TableElement", elem)
        scene_id = self._current_scene_id or ""
        self._table_renderer.render(table, scene_id)

    # -- plot rendering --------------------------------------------------------

    def _render_plot(self, elem: Element) -> None:
        """Delegate plot rendering to the extracted PlotRenderer."""
        self._plot_renderer.render(cast("PlotElement", elem))

    # -- modal rendering -------------------------------------------------------

    def _render_modal(self, elem: Element) -> None:
        """Delegate modal rendering to the extracted ModalRenderer."""
        self._modal_renderer.render(cast("ModalElement", elem))

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
        try:
            if opened:
                renderer.paint()
                # Dialog children are ABC Buttons; the legacy dispatch is typed
                # for the wire-kind union, of which ButtonElement is a member.
                for child in elem.children:
                    self.render_element(cast("Element", child))
        finally:
            # ``end`` closes the popup and applies the dialog's tooltip; run it
            # even if a child raises so the opened modal surface stays balanced.
            renderer.end(opened=opened)

    # -- draw element rendering ------------------------------------------------

    def _render_draw(self, elem: Element) -> None:
        """Delegate a DrawElement to the extracted ``DrawElementRenderer``."""
        if not isinstance(elem, DrawElement):
            msg = f"_render_draw expected DrawElement; got {type(elem).__name__}"
            raise TypeError(msg)
        self._draw_element_renderer.render(elem)
