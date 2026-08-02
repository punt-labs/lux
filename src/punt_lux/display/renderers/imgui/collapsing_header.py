# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiCollapsingHeaderRenderer — the interactive ABC collapsing-header seam.

``begin`` writes the *effective* open state — the toggle the user has in flight
if there is one, the Hub-authoritative flag otherwise — into ImGui's stored
state via ``set_next_item_open``, then reads the bool ImGui returns. A ``False``
return makes the ABC render template skip the body, so a collapsed section draws
nothing for free.

Writing the effective state rather than the raw Hub flag is what keeps one click
to one visible step: between the click and the Hub's confirming re-push the Hub
flag still holds the pre-click value, and writing it back would snap the section
shut for the length of the round trip. ``HeaderOpenArbiter`` owns that decision
and the slot behind it.

The same value gates the fire. ImGui returns what was written except on the
frame the user clicks the disclosure triangle, so a difference is a genuine user
toggle and nothing else: a Hub-driven change is never a re-fire, and neither is
any later frame of the click's own window, because the fired value is by then
the effective one. That fires ``HeaderToggled`` through the element's handler
registry, which the Display has wrapped for remote dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.header_open_arbiter import HeaderOpenArbiter
from punt_lux.domain.container_interaction import HeaderToggled
from punt_lux.domain.ids import ClientId, ElementId, SceneId

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement

__all__ = ["ImGuiCollapsingHeaderRenderer"]


@final
class ImGuiCollapsingHeaderRenderer:
    """Paint a CollapsingHeaderElement, honouring the effective ``open`` flag."""

    _elem: CollapsingHeaderElement
    _factory: ImGuiRendererFactory

    def __new__(
        cls, elem: CollapsingHeaderElement, factory: ImGuiRendererFactory
    ) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Render the effective open state; return whether the body renders.

        The tooltip attaches here, right after the header item: ``is_item_hovered``
        tracks the last item, so applying it in ``end`` would bind to the last child.
        """
        arbiter = self._arbiter()
        effective = arbiter.effective_open(authoritative=self._elem.open)
        imgui.set_next_item_open(effective)
        reported = imgui.collapsing_header(f"{self._elem.label}##{self._elem.id}")
        self._factory.apply_tooltip(self._elem)
        if reported != effective:
            arbiter.note_pending(fired=reported)
            self._elem.fire(self._toggle_event(open_=reported))
        return reported

    def _toggle_event(self, *, open_: bool) -> HeaderToggled:
        """Return the event announcing the user's toggle to the owning Hub."""
        return HeaderToggled(
            scene_id=SceneId("__display__"),
            element_id=ElementId(self._elem.id),
            owner_id=ClientId("__display__"),
            open_=open_,
        )

    def _arbiter(self) -> HeaderOpenArbiter:
        """Return an arbiter bound to the current per-scene widget state."""
        return HeaderOpenArbiter.for_element(self._factory.widget_state, self._elem)

    def paint(self) -> None:
        """No-op — a container's only body is its children (default recursion)."""

    def end(self, *, opened: bool) -> None:
        """No matching close call; the tooltip attached to the header in ``begin``."""
        _ = opened
