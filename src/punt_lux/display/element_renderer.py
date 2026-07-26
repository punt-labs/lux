# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render protocol Element dataclasses as ImGui widgets."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar, Self, cast

from imgui_bundle import imgui

from punt_lux.display.renderers.container_renderer import ContainerRenderer
from punt_lux.display.renderers.draw_element_renderer import DrawElementRenderer
from punt_lux.display.renderers.modal_renderer import ModalRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.protocol.elements.graphics import DrawElement
from punt_lux.scene import WidgetState

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol import Element
    from punt_lux.protocol.elements.layout import LegacyModalElement
    from punt_lux.types import EmitEventFn

logger = logging.getLogger(__name__)

# Callback type for checking/clearing dirty window state owned by SceneManager.
type DirtyWindowFn = Callable[[str], bool]


class ElementRenderer:
    """Render protocol Element dataclasses as ImGui widgets.

    A thin dispatcher: migrated kinds resolve their adapter through the
    ``ImGuiRendererFactory`` (the one render-side authority); the still-legacy
    composites paint through the small set of extracted renderer classes this
    owns. It holds no per-kind surface for the migrated kinds — every display
    leaf is now on the factory path — that duplication moved onto the factory.
    """

    _widget_state: WidgetState
    _table_renderer: TableRenderer
    _emit_event: EmitEventFn
    _current_scene_id: str | None
    _check_dirty_window: DirtyWindowFn
    # Resolves every migrated kind's adapter and owns the one shared tooltip pass.
    _imgui_renderer_factory: ImGuiRendererFactory
    _draw_element_renderer: DrawElementRenderer
    # Legacy composites: containers recurse their children back through
    # ``render_element``; modal paints its own extracted surface.
    _container_renderer: ContainerRenderer
    _modal_renderer: ModalRenderer

    # Legacy string dispatch — the still-legacy kinds. Shrinks as kinds migrate;
    # ABC-migrated kinds resolve through the factory adapter, never here.
    _RENDERERS: ClassVar[dict[str, str]] = {
        "draw": "_render_draw",
        "group": "_render_group",
        "tab_bar": "_render_tab_bar",
        "collapsing_header": "_render_collapsing_header",
        "window": "_render_window",
        "table": "_render_table",
        "modal": "_render_modal",
    }

    # The legacy kinds that paint one self-contained widget rather than recursing
    # children. They record geometry through the same ``measuring`` group the ABC
    # leaf template uses; the remaining legacy kinds are containers whose children
    # record as they recurse, so the container itself records nothing.
    _LEGACY_LEAF_KINDS: ClassVar[frozenset[str]] = frozenset({"draw", "table"})

    # Renderer attrs owning per-scene WidgetState; the setter forwards scene switches.
    _WIDGET_STATE_RENDERERS: ClassVar[tuple[str, ...]] = (
        "_container_renderer",
        "_modal_renderer",
    )

    def __new__(
        cls,
        widget_state: WidgetState,
        table_renderer: TableRenderer,
        emit_event: EmitEventFn,
        check_dirty_window: DirtyWindowFn,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._table_renderer = table_renderer
        self._emit_event = emit_event
        self._check_dirty_window = check_dirty_window
        self._current_scene_id = None
        self._draw_element_renderer = DrawElementRenderer()
        self._container_renderer = ContainerRenderer(
            widget_state, check_dirty_window, self.render_element, self._record_window
        )
        self._modal_renderer = ModalRenderer(
            widget_state, emit_event, self.render_element, self._record_window
        )
        return self

    def _record_window(self, element_id: str, kind: str) -> None:
        """Record a legacy window-like element's rect through the factory geometry.

        Resolves the factory at call time — it is bound after construction — so a
        legacy window or modal records its window rect and stack index like the
        ABC window/modal/dialog adapters, keeping the geometry map total.
        """
        self._imgui_renderer_factory.geometry.record_window(element_id, kind)

    @property
    def element_kind_count(self) -> int:
        """Return the number of distinct element kinds the Display can paint.

        The honest fork total: the legacy string kinds and the ABC registry's
        migrated kinds, de-duplicated (a container kind exists in both the
        legacy table and the ABC registry during the fork).
        """
        return len(set(self._RENDERERS) | DEFAULT_ABC_REGISTRY.all_kinds)

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
        legacy string dispatch, followed by the shared tooltip pass.
        """
        if self._imgui_renderer_factory.handles(elem):
            self._render_via_factory(elem)
            return
        self._render_legacy(elem)
        self._imgui_renderer_factory.apply_tooltip(elem)

    def _render_legacy(self, elem: Element) -> None:
        """Paint a still-legacy kind through the string dispatch.

        A legacy leaf paints one self-contained widget inside the geometry
        ``measuring`` group — the same the ABC leaf template uses, keyed the same
        way — so a painted table or plot appears in the geometry map rather than
        reading as "did not paint". A legacy container records nothing itself; its
        children record as they recurse. An unknown kind paints the marker.
        """
        method_name = self._RENDERERS.get(elem.kind)
        if method_name is None:
            self._render_unsupported(elem.kind)
        elif elem.kind in self._LEGACY_LEAF_KINDS:
            self._render_measured_leaf(elem)
        else:
            getattr(self, method_name)(elem)

    @staticmethod
    def _render_unsupported(kind: str) -> None:
        """Paint the fallback marker for a kind with no legacy renderer."""
        imgui.text(f"[unsupported element: {kind}]")

    def _render_measured_leaf(self, elem: Element) -> None:
        """Paint a legacy leaf inside the geometry ``measuring`` group."""
        method_name = self._RENDERERS[elem.kind]
        with self._imgui_renderer_factory.geometry.measuring(elem.id, elem.kind):
            getattr(self, method_name)(elem)

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

    # -- table / modal rendering -----------------------------------------------

    def _render_table(self, elem: Element) -> None:
        """Delegate table rendering to the extracted TableRenderer."""
        from punt_lux.protocol import TableElement

        table = cast("TableElement", elem)
        scene_id = self._current_scene_id or ""
        self._table_renderer.render(table, scene_id)

    def _render_modal(self, elem: Element) -> None:
        """Delegate legacy modal rendering to the extracted ModalRenderer."""
        self._modal_renderer.render(cast("LegacyModalElement", elem))

    # -- draw element rendering ------------------------------------------------

    def _render_draw(self, elem: Element) -> None:
        """Delegate a DrawElement to the extracted ``DrawElementRenderer``."""
        if not isinstance(elem, DrawElement):
            msg = f"_render_draw expected DrawElement; got {type(elem).__name__}"
            raise TypeError(msg)
        self._draw_element_renderer.render(elem)
