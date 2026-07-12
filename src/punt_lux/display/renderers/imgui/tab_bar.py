# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiTabBarRenderer — the interactive ABC tab-bar seam.

Satisfies the ``TabContainerRenderer`` sub-protocol: ``begin`` / ``paint`` /
``end`` open and close the tab-bar surface, ``begin_tab`` / ``end_tab`` bracket
each tab. ``begin_tab`` HONOURS the Hub-authoritative active tab (force-selecting
the matching tab the frame a fresh Hub value arrives) and FIRES ``tab_changed``
on a genuine user switch.

Echo-suppression: the honoured value is recorded per-scene in ``WidgetState``.
Before any value is honoured the slot holds ``_UNHONOURED`` — never a tab id and
never equal to ``active`` — so the first frame treats a non-first declared
``active_tab`` as a fresh Hub value: it force-selects that tab and suppresses
the fire, stopping ImGui's tab-0 default from clobbering the declared selection
with a bogus ``TabChanged``. A later Hub-driven change (``active`` differs from
the last honoured value) likewise force-selects without firing, so no
fire -> Hub -> re-push -> fire loop can run. A user switch (``active`` unchanged,
a different tab reports selected) fires exactly once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

from punt_lux.domain.container_interaction import TabChanged
from punt_lux.domain.ids import ClientId, ElementId, SceneId

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.tab import Tab
    from punt_lux.protocol.elements.tab_bar import TabBarElement

__all__ = ["ImGuiTabBarRenderer"]

_UNHONOURED = "\x00unhonoured"  # no Hub active tab honoured yet this scene


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
        self._factory.widget_state.set(self._honoured_key(), self._elem.active_tab)

    def begin_tab(self, tab: Tab, *, active: str) -> bool:
        """Open one tab item, honouring the Hub value and firing on a user switch."""
        last = self._factory.widget_state.get(self._honoured_key(), _UNHONOURED)
        flags = self._select_flags(tab.tab_id, active, last)
        selected = imgui.begin_tab_item(f"{tab.label}##{tab.tab_id}", None, flags)[0]
        if self._is_user_switch(
            selected=selected, tab_id=tab.tab_id, active=active, last=last
        ):
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

    def _honoured_key(self) -> str:
        """Return the WidgetState key holding the last-honoured active tab."""
        return f"{self._elem.id}:active_honoured"

    @staticmethod
    def _select_flags(tab_id: str, active: str, last: str) -> int:
        """Force-select this tab when the Hub active tab changed this frame."""
        if active != last and tab_id == active:
            return int(imgui.TabItemFlags_.set_selected.value)
        return 0

    @staticmethod
    def _is_user_switch(*, selected: bool, tab_id: str, active: str, last: str) -> bool:
        """Return whether this reported selection is a genuine user tab switch.

        A tab not reported selected, or already active, is no switch. A frame
        that honoured a fresh Hub value (``active`` differs from ``last``, which
        on the first frame is ``_UNHONOURED``) is the echo — it does not fire.
        """
        if not selected or tab_id == active:
            return False
        return active == last
