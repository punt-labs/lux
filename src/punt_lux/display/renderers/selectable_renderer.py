# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SelectableElement — emits an ImGui selectable list row."""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.tracing import trace

__all__ = ["SelectableRenderer"]


class SelectableRenderer:
    """Render a SelectableElement via imgui.selectable, honouring the Hub value.

    ``render`` passes ``elem.selected`` — the Hub-authoritative state — to
    ``imgui.selectable`` on every frame, so an agent-driven value change is
    reflected on the next render rather than one frame late or never. The
    renderer keeps no per-frame copy of the value: the element is the single
    source of truth and the widget is a pure function of it.

    Echo-suppression is free here. ``imgui.selectable`` reports ``clicked``
    only on a genuine user click; painting the Hub value programmatically
    leaves it False. A Hub re-push carrying the same value therefore never
    fires, so the fire -> Hub -> re-push -> fire loop cannot form. On a real
    click it fires ``ValueChanged`` through the element's handler registry,
    which the Display has wrapped for remote dispatch by
    ``DisplayServer._wrap_abc_elements`` (via ``elem.wrap_handlers_for_remote``):
    the wrapper sends the invocation to the Hub instead of running the real
    handler body locally.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @trace
    def render(self, elem: SelectableElement) -> None:
        clicked, value = imgui.selectable(f"{elem.label}##{elem.id}", elem.selected)
        if clicked:
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=value,
                )
            )
