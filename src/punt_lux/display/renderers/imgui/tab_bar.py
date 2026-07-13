# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiTabBarRenderer — the thin ImGui adapter for the ABC tab-bar seam.

``begin`` / ``paint`` / ``end`` bracket the tab-bar surface and ``begin_tab`` /
``end_tab`` bracket each tab (``TabContainerRenderer``). The fire/honour decision
lives in ``TabSelectionArbiter``; this adapter renders its verdicts, holding no state.
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
        """Close the surface, recording the honoured active tab only if it opened.

        A not-opened frame (a tab bar in a collapsed collapsing_header) drew no tab
        item and force-selected nothing; honour written there would falsely mark the
        Hub value honoured, so the frame the bar first opens would skip first-frame
        force-selection and misread ImGui's tab-0 default as a spurious user switch.
        """
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
