"""The input_text buffer/honour arbiter — the honour decision, imgui-free.

An ``input_text`` carries one Hub-authoritative ``value``, but the field also
holds the user's in-progress typing between keystrokes and the Hub's echo of an
edit. The arbiter reconciles the two from two per-scene ``WidgetState`` slots so
the fragile "honour vs keep typing" decision is testable without a live ImGui
frame.

The *buffer* slot (the element's own id) holds the string handed to
``imgui.input_text`` each frame — the user's live text. The *honoured* slot
(default ``_UNHONOURED``) records the last ``value`` a frame reconciled with the
Hub. Each frame, a ``value`` differing from the honoured value is a genuine
Hub drive: the buffer is replaced and the value honoured. A ``value`` equal to
the honoured value is no drive, so the stored buffer survives — the user's
in-progress text is never reset by the Hub's own lagging echo.

A user edit only stores the new buffer; it does *not* advance the honoured slot.
That is deliberate: through the click-to-echo latency window the Display copy's
``value`` still reads the pre-edit text, so honouring the edit immediately would
make that stale ``value`` look like a Hub drive and clobber the typing. Leaving
the honoured value at the pre-edit text keeps the stale window a no-op; the
Hub's echo of the typed text then advances the honoured slot once, harmlessly,
with the buffer already equal to it.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["InputTextArbiter"]

_UNHONOURED = "\x00unhonoured"  # no Hub value honoured yet this element


@final
class InputTextArbiter:
    """Arbitrate an input_text's rendered buffer from its two WidgetState slots."""

    _state: WidgetState
    _buffer_key: str
    _honoured_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._buffer_key = element_id
        self._honoured_key = f"{element_id}{WidgetState.INPUT_HONOURED_SUFFIX}"
        return self

    def buffer(self, value: str) -> str:
        """Return the text to render, honouring a Hub-driven value change.

        A ``value`` differing from the last honoured value is a Hub drive: the
        buffer is synced to it and the value recorded honoured. Otherwise the
        stored buffer — the user's in-progress text — is returned untouched.
        """
        if value != self._honoured:
            self._state.set(self._buffer_key, value)
            self._state.set(self._honoured_key, value)
            return value
        return str(self._state.get(self._buffer_key, value))

    def record_edit(self, text: str) -> None:
        """Store a user edit as the buffer without honouring it.

        Not honouring the edit is what protects the in-progress text: while the
        Hub's echo is in flight the Display copy's ``value`` is still the
        pre-edit text, and leaving the honoured value there keeps ``buffer`` a
        no-op for those frames rather than resetting to the stale value.
        """
        self._state.set(self._buffer_key, text)

    @property
    def _honoured(self) -> str:
        """Return the last honoured value, or ``_UNHONOURED`` before the first."""
        return str(self._state.get(self._honoured_key, _UNHONOURED))
