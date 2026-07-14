"""The input_text buffer/commit arbiter — the honour-or-defer decision, imgui-free.

An ``input_text`` carries one Hub-authoritative ``value``, but while the user
edits the field the *local buffer* — not the Hub value — is authoritative. The
arbiter encodes the controlled-input-over-latency rule (how form libraries handle
a slow round trip) so the "honour vs keep typing" decision is testable without a
live ImGui frame.

Idle: the rendered text is ``elem.value`` each frame, so an agent-driven change
appears next frame (checkbox-style). Editing: the buffer is authoritative and a
Hub-driven ``value`` is ignored, so two edits in flight before a round trip
returns cannot clobber the live text. Exactly one ``ValueChanged`` fires on
commit (blur or Enter), never per keystroke — no keystroke-versus-echo race.

Commit releases the buffer, so the field returns to honouring the Hub while the
committed text is still in flight: until the Hub echoes it back, an idle frame
renders the pre-echo ``elem.value``. That fire-then-echo latency is intended —
every interactive element carries it — not a lost edit.

The buffer lives under the element's own id; the editing flag under
``INPUT_EDITING_SUFFIX``. Both survive a whole-UI re-push (ImGui keeps the widget
active across the resend), and both are cleared when the element is removed.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["InputTextArbiter"]


@final
class InputTextArbiter:
    """Resolve an input_text's rendered text under the commit-on-idle rule."""

    _state: WidgetState
    _buffer_key: str
    _editing_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._buffer_key = element_id
        self._editing_key = f"{element_id}{WidgetState.INPUT_EDITING_SUFFIX}"
        return self

    def resolve(self, hub_value: str) -> str:
        """Return the buffer while editing (protecting live typing), else the
        Hub value — the text ImGui renders this frame.
        """
        if self._editing:
            return self._state.get_str(self._buffer_key)
        return hub_value

    def keep(self, text: str) -> None:
        """Record ``text`` as the frame's authoritative buffer (the field is active)."""
        self._state.set(self._editing_key, value=True)
        self._state.set(self._buffer_key, text)

    def release(self) -> None:
        """Mark the field idle and drop the buffer so ``resolve`` honours the Hub."""
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)

    @property
    def _editing(self) -> bool:
        """Return whether the field was being edited as of the last frame."""
        return self._state.get(self._editing_key, default=False) is True
