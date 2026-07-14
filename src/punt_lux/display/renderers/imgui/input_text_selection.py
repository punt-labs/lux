"""The input_text buffer/commit arbiter — the honour-or-defer decision, imgui-free.

An ``input_text`` carries one Hub-authoritative ``value``, but while the user
edits the field the *local buffer* — not the Hub value — is authoritative. The
arbiter encodes the controlled-input-over-latency rule (how form libraries handle
a slow round trip) so the "honour vs keep typing" decision is testable without a
live ImGui frame.

Idle, no commit outstanding: the rendered text is ``elem.value`` each frame, so
an agent-driven change appears next frame (checkbox-style). Editing: the buffer
is authoritative and a Hub-driven ``value`` is ignored, so two edits in flight
before a round trip returns cannot clobber the live text. Exactly one
``ValueChanged`` fires on commit (blur or Enter), never per keystroke.

Deferring begins on the first genuine edit, not on mere focus: a focused field
that has not been edited still honours the Hub, so an echo arriving mid-focus
reaches the display. A field defers only after ``observe`` sees a real edit.

Commit does not drop back to the raw Hub value. The Hub and Display are separate
processes: a committed value travels to the Hub and only returns as ``elem.value``
after an echo-latency window. Through that window the arbiter honours the
committed value locally — the optimistic echo — so a re-focus or a keystroke that
lands in the window builds on the value just committed, not on the stale pre-echo
one. ``resolve`` keeps honouring the committed value until the Hub value moves off
the value observed at commit time (the echo landing, or an agent override), then
clears the record and honours the Hub again.

The buffer lives under the element's own id; the editing flag and the two
commit-echo slots under their suffixes. All survive a whole-UI re-push (a commit
may still be in flight across the resend) and are cleared when the element is
removed.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["InputTextArbiter"]


@final
class InputTextArbiter:
    """Resolve an input_text's rendered text under the commit-echo rule."""

    _state: WidgetState
    _buffer_key: str
    _editing_key: str
    _committed_key: str
    _commit_hub_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._buffer_key = element_id
        self._editing_key = f"{element_id}{WidgetState.INPUT_EDITING_SUFFIX}"
        self._committed_key = f"{element_id}{WidgetState.INPUT_COMMITTED_SUFFIX}"
        self._commit_hub_key = f"{element_id}{WidgetState.INPUT_COMMIT_HUB_SUFFIX}"
        return self

    def resolve(self, hub_value: str) -> str:
        """Return the text ImGui renders this frame.

        While editing, the buffer wins (protecting live typing). Otherwise, if a
        committed value is recorded and the Hub value still matches the value
        observed at commit time, honour the committed value — the optimistic echo
        through the latency window. Once the Hub value has moved, forget the
        commit and honour the Hub.
        """
        if self._editing:
            return self._state.get_str(self._buffer_key)
        committed = self._state.get(self._committed_key)
        if committed is not None and hub_value == self._state.get(self._commit_hub_key):
            return str(committed)
        self._forget_commit()
        return hub_value

    def observe(self, *, edited: bool, text: str) -> None:
        """Record ``text`` as the buffer and begin deferring — but only on a real edit.

        A frame with a genuine edit (or a field already editing) is authoritative
        over its buffer. A focused-but-not-yet-edited frame is left honouring, so
        an echo can still reach it.
        """
        if edited or self._editing:
            self._state.set(self._editing_key, value=True)
            self._state.set(self._buffer_key, text)

    def commit(self, text: str, hub_value: str) -> None:
        """Record the committed value and the Hub value observed at commit time.

        The editing flag is not cleared here; the deactivation frame's ``release``
        does that. Recording the pair opens the optimistic-echo window ``resolve``
        honours until the Hub value moves off ``hub_value``.
        """
        self._state.set(self._committed_key, text)
        self._state.set(self._commit_hub_key, hub_value)

    def release(self) -> None:
        """Mark the field idle and drop the buffer, keeping the commit-echo record.

        The committed value stays honoured until ``resolve`` observes the Hub
        value has moved past the commit-time value; only then is it forgotten.
        """
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)

    @property
    def _editing(self) -> bool:
        """Return whether the field was being edited as of the last frame."""
        return self._state.get(self._editing_key, default=False) is True

    def _forget_commit(self) -> None:
        """Drop the commit-echo record once the Hub value has moved past it."""
        self._state.discard(self._committed_key)
        self._state.discard(self._commit_hub_key)
