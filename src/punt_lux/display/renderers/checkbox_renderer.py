# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for CheckboxElement — emits an ImGui checkbox."""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.tracing import trace

__all__ = ["CheckboxRenderer"]


class CheckboxRenderer:
    """Render a CheckboxElement via imgui.checkbox, honouring the Hub value.

    ``render`` passes ``elem.value`` — the Hub-authoritative state — to
    ``imgui.checkbox`` on every frame, so an agent-driven value change is
    reflected on the next render rather than one frame late or never. The
    renderer keeps no per-frame copy of the value: the element is the single
    source of truth and the widget is a pure function of it.

    Echo-suppression is free here. ``imgui.checkbox`` reports ``changed``
    only on a genuine user click; painting the Hub value programmatically
    leaves it False. A Hub re-push carrying the same value therefore never
    fires, so the fire -> Hub -> re-push -> fire loop cannot form. On a real
    toggle it fires ``ValueChanged`` through the element's handler registry,
    which the Display has wrapped for remote dispatch by
    ``DisplayServer._wrap_abc_elements`` (via ``elem.wrap_handlers_for_remote``):
    the wrapper sends the invocation to the Hub instead of running the real
    handler body locally.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @trace
    def render(self, elem: CheckboxElement) -> None:
        changed, value = imgui.checkbox(f"{elem.label}##{elem.id}", elem.value)
        if changed:
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=value,
                )
            )
