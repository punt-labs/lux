# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render protocol Element dataclasses as ImGui widgets."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import fields
from typing import TYPE_CHECKING, ClassVar, Self, cast

from punt_lux.display.renderers import (
    ImageRenderer,
    MarkdownRenderer,
    SeparatorRenderer,
    SpinnerRenderer,
)
from punt_lux.display.renderers.container_renderer import ContainerRenderer
from punt_lux.display.renderers.draw_element_renderer import DrawElementRenderer
from punt_lux.display.renderers.modal_renderer import ModalRenderer
from punt_lux.display.renderers.plot_renderer import PlotRenderer
from punt_lux.display.renderers.tree_renderer import TreeRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.protocol.elements.graphics import DrawElement
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.spinner import SpinnerElement
from punt_lux.scene import WidgetState

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol import Element
    from punt_lux.protocol.elements.layout import ModalElement, TreeElement
    from punt_lux.protocol.elements.plot_element import PlotElement
    from punt_lux.types import EmitEventFn

logger = logging.getLogger(__name__)

# Callback type for checking/clearing dirty window state owned by SceneManager.
type DirtyWindowFn = Callable[[str], bool]


class ElementRenderer:
    """Render protocol Element dataclasses as ImGui widgets.

    A thin dispatcher: migrated kinds resolve their adapter through the
    ``ImGuiRendererFactory`` (the one render-side authority); the residual
    pre-ABC leaves and the still-legacy composites paint through the small
    set of extracted renderer classes this owns. It holds no per-kind surface
    for the migrated kinds — that duplication moved onto the factory.
    """

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _table_renderer: TableRenderer
    _emit_event: EmitEventFn
    _current_scene_id: str | None
    _check_dirty_window: DirtyWindowFn
    # Resolves every migrated kind's adapter and owns the one shared tooltip pass.
    _imgui_renderer_factory: ImGuiRendererFactory
    # Pre-ABC display leaves with no adapter yet — the residual dispatch table.
    _image_renderer: ImageRenderer
    _separator_renderer: SeparatorRenderer
    _spinner_renderer: SpinnerRenderer
    _markdown_renderer: MarkdownRenderer
    _draw_element_renderer: DrawElementRenderer
    # Legacy composites: containers recurse their children back through
    # ``render_element``; tree/plot/modal paint their own extracted surface.
    _container_renderer: ContainerRenderer
    _tree_renderer: TreeRenderer
    _plot_renderer: PlotRenderer
    _modal_renderer: ModalRenderer

    # Legacy string dispatch — the still-legacy kinds. Shrinks as kinds migrate;
    # ABC-migrated kinds resolve through the factory adapter, never here.
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
    }

    # Pre-ABC display leaves with no adapter yet. This table only loses rows —
    # every new kind lands on the ABC/factory path — and empties when these
    # four migrate.
    _RESIDUAL_DISPATCH: ClassVar[tuple[tuple[type, str], ...]] = (
        (ImageElement, "_image_renderer"),
        (SeparatorElement, "_separator_renderer"),
        (SpinnerElement, "_spinner_renderer"),
        (MarkdownElement, "_markdown_renderer"),
    )
    # Derived from the dispatch table, not double-listed. Each residual element is
    # a slotted dataclass: read the ``kind`` field default, not the slot descriptor.
    _RESIDUAL_KINDS: ClassVar[frozenset[str]] = frozenset(
        str(next(f.default for f in fields(element_type) if f.name == "kind"))
        for element_type, _ in _RESIDUAL_DISPATCH
    )

    # Renderer attrs owning per-scene WidgetState; the setter forwards scene switches.
    _WIDGET_STATE_RENDERERS: ClassVar[tuple[str, ...]] = (
        "_container_renderer",
        "_modal_renderer",
    )

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
        self._image_renderer = ImageRenderer(texture_cache)
        self._separator_renderer = SeparatorRenderer()
        self._spinner_renderer = SpinnerRenderer()
        self._markdown_renderer = MarkdownRenderer()
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

    @property
    def element_kind_count(self) -> int:
        """Return the number of distinct element kinds the Display can paint.

        The honest fork total: the legacy string kinds, the residual leaves,
        and the ABC registry's migrated kinds, de-duplicated (a container kind
        exists in both the legacy table and the ABC registry during the fork).
        """
        return len(
            set(self._RENDERERS) | self._RESIDUAL_KINDS | DEFAULT_ABC_REGISTRY.all_kinds
        )

    @property
    def widget_state(self) -> WidgetState:
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        self._widget_state = value
        for attr in self._WIDGET_STATE_RENDERERS:
            getattr(self, attr).widget_state = value
        # The ABC adapters read per-scene state (echo suppression, edit buffers)
        # through the factory; re-thread it so a scene switch reaches them too.
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
        """Dispatch an element to its renderer (factory adapter or legacy path).

        A migrated kind — including a leaf nested in a legacy container — resolves
        its adapter through the factory (DES-042: the same adapter the top-level
        ABC path uses, so pixels are byte-identical). Everything else falls to the
        residual leaves, then the legacy string dispatch, then the unsupported
        fallback, each followed by the shared tooltip pass.
        """
        from imgui_bundle import imgui

        factory = self._imgui_renderer_factory
        if factory.handles(elem):
            self._render_via_factory(elem)
            return
        if not self._dispatch_residual(elem):
            method_name = self._RENDERERS.get(elem.kind)
            if method_name is not None:
                getattr(self, method_name)(elem)
            else:
                imgui.text(f"[unsupported element: {elem.kind}]")
        self._imgui_renderer_factory.apply_tooltip(elem)

    def _render_via_factory(self, elem: AbcElement) -> None:
        """Paint a factory-backed ABC element (leaf or transitional dialog).

        Drives the shared ``begin`` → ``paint`` → ``end`` adapter template. The
        adapter applies its own tooltip, so the generic pass is skipped here. A
        leaf recurses nothing; the transitional dialog recurses its child Buttons
        back through ``render_element`` so they paint via the same adapter path.

        Resolves the Display's real factory directly rather than ``elem.render()``:
        an ABC leaf nested in a legacy container never has its own factory
        rebound (only top-level ABC subtrees do), so its ``render()`` would
        resolve the fail-loud sentinel.
        """
        adapter = self._imgui_renderer_factory(elem)
        opened = adapter.begin()
        try:
            if opened:
                adapter.paint()
                for child in elem.child_elements():
                    self.render_element(cast("Element", child))
        finally:
            # ``end`` closes any opened surface and applies the adapter's tooltip;
            # run it even if a child raises so an opened modal stays balanced.
            adapter.end(opened=opened)

    def _dispatch_residual(self, elem: Element) -> bool:
        """Route the pre-ABC display leaves that have no adapter yet.

        Returns True iff ``elem`` is one of the four leaves (image, separator,
        spinner, markdown) still painted by a stateless renderer here.
        """
        for element_type, renderer_attr in self._RESIDUAL_DISPATCH:
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

    # -- tree / table / plot / modal rendering ---------------------------------

    def _render_tree(self, elem: Element) -> None:
        """Delegate tree rendering to the extracted TreeRenderer."""
        self._tree_renderer.render(cast("TreeElement", elem))

    def _render_table(self, elem: Element) -> None:
        """Delegate table rendering to the extracted TableRenderer."""
        from punt_lux.protocol import TableElement

        table = cast("TableElement", elem)
        scene_id = self._current_scene_id or ""
        self._table_renderer.render(table, scene_id)

    def _render_plot(self, elem: Element) -> None:
        """Delegate plot rendering to the extracted PlotRenderer."""
        self._plot_renderer.render(cast("PlotElement", elem))

    def _render_modal(self, elem: Element) -> None:
        """Delegate modal rendering to the extracted ModalRenderer."""
        self._modal_renderer.render(cast("ModalElement", elem))

    # -- draw element rendering ------------------------------------------------

    def _render_draw(self, elem: Element) -> None:
        """Delegate a DrawElement to the extracted ``DrawElementRenderer``."""
        if not isinstance(elem, DrawElement):
            msg = f"_render_draw expected DrawElement; got {type(elem).__name__}"
            raise TypeError(msg)
        self._draw_element_renderer.render(elem)
