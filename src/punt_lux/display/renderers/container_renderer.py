# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render layout-container elements — group, tab bar, collapsing header, window.

Split out of ``ElementRenderer`` so the general element dispatch and the
container-layout subsystem each stay one responsibility (PY-IC-6). Child
elements recurse back through the ``render_child`` callback the owning
``ElementRenderer`` supplies, so this renderer never imports the dispatch
table and never learns about non-container kinds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast, final

from imgui_bundle import imgui

if TYPE_CHECKING:
    from punt_lux.protocol import (
        CollapsingHeaderElement,
        Element,
        LegacyGroupElement,
        TabBarElement,
        WindowElement,
    )
    from punt_lux.scene import WidgetState

__all__ = ["ContainerRenderer"]

# Recurse a child element back through the owning ElementRenderer's dispatch.
type RenderChildFn = Callable[[Element], None]
# Check-and-clear a window's dirty flag, owned by SceneManager.
type DirtyWindowFn = Callable[[str], bool]


@final
class ContainerRenderer:
    """Paint layout containers, recursing children via a render callback."""

    _widget_state: WidgetState
    _check_dirty_window: DirtyWindowFn
    _render_child: RenderChildFn

    # (WindowElement attribute, ImGui WindowFlags_ member) pairs — a data
    # table replaces a six-branch if-cascade so folding the flags is one loop.
    _WINDOW_FLAG_ATTRS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("no_move", "no_move"),
        ("no_resize", "no_resize"),
        ("no_collapse", "no_collapse"),
        ("no_title_bar", "no_title_bar"),
        ("no_scrollbar", "no_scrollbar"),
        ("auto_resize", "always_auto_resize"),
    )

    def __new__(
        cls,
        widget_state: WidgetState,
        check_dirty_window: DirtyWindowFn,
        render_child: RenderChildFn,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._check_dirty_window = check_dirty_window
        self._render_child = render_child
        return self

    @property
    def widget_state(self) -> WidgetState:
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        self._widget_state = value

    # -- group -----------------------------------------------------------------

    def render_group(self, elem: Element) -> None:
        """Render a group's children in rows, columns, or paged layout."""
        grp = cast("LegacyGroupElement", elem)
        layout = grp.layout

        if layout == "paged":
            self._render_paged_group(grp)
            return

        for i, child in enumerate(grp.children):
            if layout == "columns" and i > 0:
                imgui.same_line()
            self._render_child(child)

    def _paged_group_state_key(self, grp_id: str, page_source: str | None) -> str:
        """Return the widget_state key for a paged group's page index."""
        return page_source if page_source else f"{grp_id}__pg_idx"

    def _paged_group_read_index(self, state_key: str, total: int) -> int:
        """Read and clamp the current page index from widget_state."""
        raw = self._widget_state.get(state_key)
        page_idx = raw if isinstance(raw, int) else 0
        return max(0, min(page_idx, total - 1)) if total else 0

    def _render_paged_group(self, grp: LegacyGroupElement) -> None:
        """Render a paged group with built-in Prev/Next navigation."""
        pages = grp.pages
        total = len(pages) if pages else 0
        page_source = grp.page_source
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
            self._render_child(child)

        if pages and 0 <= page_idx < total:
            for child in pages[page_idx]:
                self._render_child(child)

    def _render_paged_inline_children(self, grp: LegacyGroupElement) -> list[Any]:
        """Render the page-source combo inline; return the remaining children.

        Children are the wire element union — heterogeneous and typed ``Any``
        on ``LegacyGroupElement`` itself, so the list stays ``Any`` at this boundary.
        """
        page_source = grp.page_source
        other_children: list[Any] = []
        for child in grp.children:
            if page_source and getattr(child, "id", None) == page_source:
                self._render_child(child)
                imgui.same_line()
            else:
                other_children.append(child)
        return other_children

    # -- tab bar ---------------------------------------------------------------

    def render_tab_bar(self, elem: Element) -> None:
        """Render a tab bar; each tab's children paint when its tab is active."""
        tb = cast("TabBarElement", elem)
        if imgui.begin_tab_bar(f"##{tb.id}"):
            for tab in tb.tabs:
                tab_label: str = tab.get("label", "Tab")
                if imgui.begin_tab_item(tab_label)[0]:
                    for child in tab.get("children", []):
                        self._render_child(child)
                    imgui.end_tab_item()
            imgui.end_tab_bar()

    # -- collapsing header -----------------------------------------------------

    def render_collapsing_header(self, elem: Element) -> None:
        """Render a collapsing header; children paint only while expanded."""
        ch = cast("CollapsingHeaderElement", elem)
        flags = imgui.TreeNodeFlags_.default_open.value if ch.default_open else 0
        if imgui.collapsing_header(f"{ch.label}##{ch.id}", flags=flags):
            for child in ch.children:
                self._render_child(child)

    # -- window ----------------------------------------------------------------

    @staticmethod
    def _window_flags(win: WindowElement) -> int:
        """Fold a WindowElement's boolean options into an ImGui flags mask."""
        flags = 0
        for attr, flag_name in ContainerRenderer._WINDOW_FLAG_ATTRS:
            if getattr(win, attr):
                flags |= getattr(imgui.WindowFlags_, flag_name).value
        return flags

    def render_window(self, elem: Element) -> None:
        """Render a floating window; children paint while it is expanded."""
        win = cast("WindowElement", elem)
        flags = self._window_flags(win)

        # check_dirty_window returns True and clears the flag when the window
        # was marked dirty by a scene update.
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
                self._render_child(child)
        imgui.end()
