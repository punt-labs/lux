"""The input_text buffer/commit arbiter — the honour-or-defer decision, imgui-free.

An ``input_text`` carries one Hub-authoritative ``value``, but while the user
edits, the *local buffer* — not the Hub value — is authoritative. The arbiter
encodes the controlled-input-over-latency rule (how form libraries handle a slow
round trip) so the honour-vs-keep-typing decision is testable without ImGui.

Idle: the rendered text is ``elem.value`` each frame, so an agent-driven change
appears next frame (checkbox-style). Editing: the buffer is authoritative and a
Hub-driven ``value`` is ignored, so two edits in flight before a round trip
returns cannot clobber live text. Deferring begins only on the first genuine
edit ``observe`` sees, not on mere focus, so an echo arriving mid-focus still
reaches an unedited field. Exactly one ``ValueChanged`` fires on commit (blur or
Enter), never per keystroke.

The Hub and Display are separate processes, so a committed value returns as
``elem.value`` only after an echo-latency window. Through that window ``resolve``
honours the committed value locally — the optimistic echo — so a re-focus or
keystroke in it builds on it; see ``resolve`` for the rule and its limits.

The buffer lives under the element's own id; the editing flag and the two
commit-echo slots under their suffixes. All survive a whole-UI re-push (a commit
may still be in flight across the resend) and are cleared on removal.
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

        Reconciliation is by value equality alone — a commit carries no echo
        token or version, and one committed/commit-hub pair holds only the latest
        commit. Two non-data-loss limits follow, each needing timing inside one
        echo round-trip (negligible on localhost): two commits within a round-trip
        can transiently revert the display to the intermediate Hub value (a
        flicker — the second commit's echo still lands); and an agent driving the
        Hub back to the exact commit-time value in the window is masked as the
        pending echo until the field next moves off it.
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

        A genuine edit (or a field already editing) is authoritative over its
        buffer; a focused-but-not-yet-edited frame is left honouring so an echo
        can still reach it.
        """
        if edited or self._editing:
            self._state.set(self._editing_key, value=True)
            self._state.set(self._buffer_key, text)

    def commit(self, text: str, hub_value: str) -> None:
        """Record the committed value and the Hub value observed at commit time.

        Opens the optimistic-echo window ``resolve`` honours until the Hub value
        moves off ``hub_value``. The editing flag is left for ``release`` to clear.
        """
        self._state.set(self._committed_key, text)
        self._state.set(self._commit_hub_key, hub_value)

    def release(self) -> None:
        """Mark the field idle and drop the buffer, keeping the commit-echo record.

        The committed value stays honoured until ``resolve`` sees the Hub value
        move past the commit-time value; only then is it forgotten.
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
