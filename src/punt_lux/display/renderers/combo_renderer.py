# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ComboElement — dropdown combo box, honouring the Hub value."""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.tracing import trace

__all__ = ["ComboRenderer"]


class ComboRenderer:
    """Render a ComboElement via imgui.combo, honouring the Hub selection.

    ``render`` passes ``elem.selected`` — the Hub-authoritative index — to
    ``imgui.combo`` on every frame, so an agent-driven change is reflected on the
    next render rather than one frame late or never. The renderer keeps no
    per-frame copy: the element is the single source of truth and the widget is a
    pure function of it.

    Echo-suppression is free. ``imgui.combo`` reports ``changed`` only on a
    genuine user pick; painting the Hub index programmatically leaves it False, so
    a Hub re-push carrying the same index never fires and the fire -> Hub ->
    re-push -> fire loop cannot form. On a real pick it fires ``ValueChanged``
    carrying the new index through the element's handler registry, which the
    Display has wrapped for D21 remote dispatch.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @trace
    def render(self, elem: ComboElement) -> None:
        label = elem.label
        items = elem.items
        if not items:
            imgui.text(f"{label}: (empty)")
            return
        changed, new_val = imgui.combo(f"{label}##{elem.id}", elem.selected, items)
        if changed:
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=new_val,
                )
            )
