# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for InputNumberElement — a commit-on-idle numeric input.

Idle, the field tracks ``elem.value``; while typing the local buffer wins and a
Hub value is deferred, so a re-push landing mid-edit cannot clobber the value
under the cursor. Exactly one ``ValueChanged`` fires per gesture, wrapped for
remote dispatch. The arbiter buffers a ``float``; the integer variant converts to
``int`` only at ``input_int`` and in the payload (``float(int)`` is exact).

Two commit conditions feed one commit call, so a frame commits at most once: a
typing gesture ends with ``is_item_deactivated_after_edit`` (blur / Enter / a
stepper release, which ``EndGroup`` propagates from the compound widget); a
discrete change on a frame that is not active is the fallback for a stepper build
that does not report the deactivate. Both drive a single ``if`` — never two
branches — so a gesture never double-fires even on a frame that satisfies both.
"""

from __future__ import annotations

from typing import Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.continuous_edit_accessors import (
    FloatValueAccessor,
)
from punt_lux.display.renderers.imgui.continuous_edit_selection import (
    ContinuousEditArbiter,
)
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["InputNumberRenderer"]

# The float accessor is stateless, so one shared instance serves every frame.
_ACCESSOR = FloatValueAccessor()


@final
class InputNumberRenderer:
    """Render an InputNumberElement under the commit-on-idle rule.

    Holds the per-scene ``WidgetState`` and builds a fresh
    ``ContinuousEditArbiter`` (with a ``FloatValueAccessor``) per frame; the
    arbiter owns the buffer/commit-echo slots, so this stays a thin ImGui seam.
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
    def render(self, elem: InputNumberElement) -> None:
        arbiter = ContinuousEditArbiter(self._widget_state, elem.id, _ACCESSOR)
        label = f"{elem.label}##{elem.id}"
        resolved = arbiter.resolve(elem.value)
        changed, new_val = self._draw(elem, label, resolved)
        active = imgui.is_item_active()
        if active:
            arbiter.observe(edited=changed, value=float(new_val))
        else:
            arbiter.release()
        committed = imgui.is_item_deactivated_after_edit()
        if committed or (changed and not active):
            self._commit(elem, arbiter, new_val)

    @staticmethod
    def _commit(
        elem: InputNumberElement,
        arbiter: ContinuousEditArbiter[float],
        new_val: int | float,
    ) -> None:
        """Fire one ValueChanged (wrapped for D21) and open the echo window."""
        elem.fire(
            ValueChanged(
                scene_id=SceneId("__display__"),
                element_id=ElementId(elem.id),
                owner_id=ClientId("__display__"),
                value=new_val,
            )
        )
        arbiter.commit(float(new_val), elem.value)

    @staticmethod
    def _draw(
        elem: InputNumberElement, label: str, resolved: float
    ) -> tuple[bool, int | float]:
        """Draw the int/float variant; the int seam coerces to ``int`` for input_int."""
        if elem.integer:
            step = int(elem.step) if elem.step is not None else 0
            return imgui.input_int(label, int(resolved), step, step * 10)
        step_f = elem.step if elem.step is not None else 0.0
        return imgui.input_float(
            label, float(resolved), step_f, step_f * 10.0, elem.format
        )
