# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiTabBarRenderer — the interactive ABC tab-bar seam.

Satisfies the ``TabContainerRenderer`` sub-protocol: ``begin`` / ``paint`` /
``end`` open and close the tab-bar surface, ``begin_tab`` / ``end_tab`` bracket
each tab. ``begin_tab`` HONOURS the Hub-authoritative active tab (force-selecting
the matching tab the frame a fresh Hub value arrives) and FIRES ``tab_changed``
on a genuine user switch.

The fire/honour decision is delegated to ``TabSelectionArbiter``, which arbitrates
from two per-scene ``WidgetState`` slots. This renderer is the thin ImGui adapter:
it translates the arbiter's decisions into ``begin_tab_item`` flags and the
``fire`` call, and keeps no selection bookkeeping of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.tab_selection import TabSelectionArbiter
from punt_lux.domain.container_interaction import TabChanged
from punt_lux.domain.ids import ClientId, ElementId, SceneId

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.tab import Tab
    from punt_lux.protocol.elements.tab_bar import TabBarElement

__all__ = ["ImGuiTabBarRenderer"]

_SET_SELECTED = int(imgui.TabItemFlags_.set_selected.value)


@final
class ImGuiTabBarRenderer:
    """Paint a TabBarElement, honouring the Hub-owned active-tab selection."""

    _elem: TabBarElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: TabBarElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Open the tab-bar surface; return whether the tab items run."""
        return imgui.begin_tab_bar(f"##{self._elem.id}")

    def paint(self) -> None:
        """No-op — a tab bar's body is its tabs' children (the render override)."""

    def end(self, *, opened: bool) -> None:
        """Close the surface and record the honoured active tab (once per frame)."""
        if opened:
            imgui.end_tab_bar()
        self._arbiter().record_honoured(self._elem.active_tab)

    def begin_tab(self, tab: Tab, *, active: str) -> bool:
        """Open one tab item, honouring the Hub value and firing on a user switch."""
        arbiter = self._arbiter()
        flags = _SET_SELECTED if arbiter.should_force_select(tab.tab_id, active) else 0
        selected = imgui.begin_tab_item(f"{tab.label}##{tab.tab_id}", None, flags)[0]
        if arbiter.should_fire(selected=selected, tab_id=tab.tab_id, active=active):
            self._elem.fire(
                TabChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(self._elem.id),
                    owner_id=ClientId("__display__"),
                    tab_id=tab.tab_id,
                )
            )
        return selected

    def end_tab(self, *, opened: bool) -> None:
        """Close the tab item ``begin_tab`` opened."""
        if opened:
            imgui.end_tab_item()

    def _arbiter(self) -> TabSelectionArbiter:
        """Return an arbiter bound to the current per-scene widget state."""
        return TabSelectionArbiter(self._factory.widget_state, self._elem.id)
