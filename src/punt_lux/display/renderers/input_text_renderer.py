# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for InputTextElement — a commit-on-idle single-line text input.

While idle the buffer is synced to the Hub-authoritative ``elem.value``; while
being edited the local buffer wins and a Hub-driven value is deferred. Exactly
one ``ValueChanged`` fires when the edit commits (blur or Enter, via
``is_item_deactivated_after_edit``), never per keystroke — so pipelined edits
cannot clobber live typing. The commit fire is wrapped for D21 remote dispatch.
"""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.input_text_selection import InputTextArbiter
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["InputTextRenderer"]


class InputTextRenderer:
    """Render an InputTextElement under the commit-on-idle rule.

    Holds the per-scene ``WidgetState`` (re-threaded on a scene switch) and
    builds a fresh ``InputTextArbiter`` per element per frame; the arbiter owns
    the buffer/editing slots, so this class stays a thin ImGui seam. The commit
    fire routes through the element's handler registry, wrapped for remote
    dispatch, so the interaction runs on the Hub, not locally.
    """

    _widget_state: WidgetState

    def __new__(cls, widget_state: WidgetState) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        return self

    @property
    def widget_state(self) -> WidgetState:
        """Return the per-scene widget state the buffer/honour slots live in."""
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        """Re-thread the renderer to the scene being rendered."""
        self._widget_state = value

    @trace
    def render(self, elem: InputTextElement) -> None:
        arbiter = InputTextArbiter(self._widget_state, elem.id)
        label = f"{elem.label}##{elem.id}"
        # A ``""`` hint renders like a plain input, so one variant covers both;
        # imgui returns the widget's current text each frame as ``text``.
        changed, text = imgui.input_text_with_hint(
            label, elem.hint, arbiter.resolve(elem.value)
        )
        if imgui.is_item_active():
            arbiter.observe(edited=changed, text=text)
        else:
            arbiter.release()
        if imgui.is_item_deactivated_after_edit():
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=text,
                )
            )
            arbiter.commit(text, elem.value)
