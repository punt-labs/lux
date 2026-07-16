# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for RadioElement — a horizontal set of radio buttons.

Stateless: ``render`` reads ``elem.selected`` — the Hub-authoritative index —
each frame and holds no per-scene copy, so an agent-driven change shows on the
next render; an empty-but-valid group paints ``f"{label}: (empty)"``. Painting
the Hub index programmatically never reports a click, so a re-push carrying the
same index cannot form a fire -> Hub -> re-push -> fire loop; only a genuine pick
of a *different* item fires ``ValueChanged``, wrapped for D21 remote dispatch.
"""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.tracing import trace

__all__ = ["RadioRenderer"]


class RadioRenderer:
    """Render a RadioElement as a horizontal list of radio buttons.

    Honours the Hub selection: each ``imgui.radio_button`` is active iff its index
    equals ``elem.selected``. A click on a different item fires ``ValueChanged``
    carrying the new index through the element's handler registry, which the
    Display has wrapped for D21 remote dispatch.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @trace
    def render(self, elem: RadioElement) -> None:
        label = elem.label
        items = elem.items
        if not items:
            imgui.text(f"{label}: (empty)")
            return
        eid = elem.id
        current = elem.selected
        if label:
            imgui.text(label)
        for i, item in enumerate(items):
            if imgui.radio_button(f"{item}##{eid}_{i}", current == i) and current != i:
                elem.fire(
                    ValueChanged(
                        scene_id=SceneId("__display__"),
                        element_id=ElementId(eid),
                        owner_id=ClientId("__display__"),
                        value=i,
                    )
                )
            if i < len(items) - 1:
                imgui.same_line()
