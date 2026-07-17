# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiCollapsingHeaderRenderer — the interactive ABC collapsing-header seam.

``begin`` honours the Hub-authoritative ``open`` flag every frame via
``set_next_item_open`` (not ``first_use_ever`` — the Hub owns the value, so it is
authoritative on every frame, not just the first), then reads the bool ImGui
returns. A ``False`` return makes the ABC render template skip the body, so a
collapsed section draws nothing for free. On a genuine user toggle — the reported
state differs from the Hub value — it fires ``HeaderToggled`` through the
element's handler registry, which the Display has wrapped for remote dispatch.

Echo-suppression: because the Hub value is honoured every frame, ImGui reports
that same value except on the frame the user clicks the disclosure triangle. So a
Hub-driven change is never a re-fire — ``_toggle_event`` returns ``None`` when the
reported state already equals the Hub ``open``, stopping a fire -> re-push loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

from punt_lux.domain.container_interaction import HeaderToggled
from punt_lux.domain.ids import ClientId, ElementId, SceneId

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement

__all__ = ["ImGuiCollapsingHeaderRenderer"]


@final
class ImGuiCollapsingHeaderRenderer:
    """Paint a CollapsingHeaderElement, honouring the Hub-owned ``open`` flag."""

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
        """Honour the Hub ``open`` flag; return whether the body renders.

        Fires ``HeaderToggled`` only on a genuine user toggle (the reported
        state differs from the honoured Hub value), never on a Hub-driven echo.
        """
        imgui.set_next_item_open(self._elem.open)
        reported = imgui.collapsing_header(f"{self._elem.label}##{self._elem.id}")
        event = self._toggle_event(reported=reported)
        if event is not None:
            self._elem.fire(event)
        return reported

    def _toggle_event(self, *, reported: bool) -> HeaderToggled | None:
        """Return the event to fire on a user toggle, or ``None`` for a Hub echo.

        A reported state equal to the honoured Hub ``open`` is either the
        initial paint or the echo of a Hub-driven change — neither re-fires.
        """
        if reported == self._elem.open:
            return None
        return HeaderToggled(
            scene_id=SceneId("__display__"),
            element_id=ElementId(self._elem.id),
            owner_id=ClientId("__display__"),
            open_=reported,
        )

    def paint(self) -> None:
        """No-op — a container's only body is its children (default recursion)."""

    def end(self, *, opened: bool) -> None:
        """Apply the hover tooltip; ``collapsing_header`` has no matching close call."""
        _ = opened
        self._factory.apply_tooltip(self._elem)
