"""The slider drag/commit arbiter — the honour-or-defer decision, imgui-free.

A ``slider`` carries one Hub-authoritative ``value`` (a ``float`` in
``[min, max]``), but while the user drags, the *local thumb position* — not the
Hub value — is authoritative. The arbiter encodes the controlled-input-over-
latency rule so the honour-vs-keep-dragging decision is testable without ImGui.

Idle: the rendered position is ``elem.value`` each frame, so an agent-driven
change appears next frame (checkbox-style). Dragging: the buffer is
authoritative and a Hub-driven ``value`` is ignored, so a Hub re-push landing
mid-drag cannot clobber the value under the user's thumb. Deferring begins only
on the first genuine drag ``observe`` sees, not on mere grab, so an echo
arriving mid-grab still reaches an ungrabbed thumb. Exactly one ``ValueChanged``
fires on release (deactivate-after-edit), never per drag frame.

The Hub and Display are separate processes, so a committed value returns as
``elem.value`` only after an echo-latency window. Through that window ``resolve``
honours the committed value locally — the optimistic echo — so a re-grab or
drag in it builds on it; see ``resolve`` for the rule and its limits.

This is the ``float`` sibling of ``InputTextArbiter``: same four slots, same
honour/defer/commit/echo control flow. Only the carried value's type differs
(``float``, read through ``WidgetState.get_float``), and there is no
empty-value special case — every ``float`` is a value, so the buffer default
is the current Hub value rather than a sentinel.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["SliderArbiter"]


@final
class SliderArbiter:
    """Resolve a slider's rendered position under the commit-echo rule."""

    _state: WidgetState
    _buffer_key: str
    _editing_key: str
    _committed_key: str
    _commit_hub_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._buffer_key = element_id
        self._editing_key = f"{element_id}{WidgetState.SLIDER_EDITING_SUFFIX}"
        self._committed_key = f"{element_id}{WidgetState.SLIDER_COMMITTED_SUFFIX}"
        self._commit_hub_key = f"{element_id}{WidgetState.SLIDER_COMMIT_HUB_SUFFIX}"
        return self

    def resolve(self, hub_value: float) -> float:
        """Return the thumb position ImGui renders this frame.

        While dragging, the buffer wins (protecting the live thumb). Otherwise,
        if a committed value is recorded and the Hub value still matches the
        value observed at commit time, honour the committed value — the
        optimistic echo through the latency window. Once the Hub value has
        moved, forget the commit and honour the Hub.

        Reconciliation is by value equality alone: a commit carries no echo
        token, and one committed/commit-hub pair holds only the latest commit.
        ``SliderElement.validate`` rejects NaN/±inf, so ``hub_value ==
        commit_hub`` stays reflexive; a ``NaN`` commit-hub would never compare
        equal, taking the forget branch and snapping the display to the raw Hub.

        Two non-data-loss limits follow from the single-slot design, each
        needing timing inside one echo round-trip (negligible on localhost):
        two commits within a round-trip can transiently revert the display to
        the intermediate Hub value (a flicker — the second commit's echo still
        lands); and an agent driving the Hub back to the exact commit-time
        value in the window is masked as the pending echo until the thumb next
        moves off it.
        """
        if self._editing:
            return self._state.get_float(self._buffer_key, default=hub_value)
        committed = self._state.get(self._committed_key)
        if committed is not None and hub_value == self._state.get(self._commit_hub_key):
            return float(committed)
        self._forget_commit()
        return hub_value

    def observe(self, *, edited: bool, value: float) -> None:
        """Record ``value`` as the buffer and begin deferring — only on a real drag.

        A genuine drag frame (or a thumb already being dragged) is authoritative
        over its buffer; a grabbed-but-not-yet-moved frame is left honouring so
        an echo can still reach it.
        """
        if edited or self._editing:
            self._state.set(self._editing_key, value=True)
            self._state.set(self._buffer_key, value)

    def commit(self, value: float, hub_value: float) -> None:
        """Record the committed value and the Hub value observed at commit time.

        Opens the optimistic-echo window ``resolve`` honours until the Hub value
        moves off ``hub_value``. The editing flag is left for ``release`` to
        clear.
        """
        self._state.set(self._committed_key, value)
        self._state.set(self._commit_hub_key, hub_value)

    def release(self) -> None:
        """Mark the thumb idle and drop the buffer, keeping the commit-echo record.

        The committed value stays honoured until ``resolve`` sees the Hub value
        move past the commit-time value; only then is it forgotten.
        """
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)

    @property
    def _editing(self) -> bool:
        """Return whether the thumb was being dragged as of the last frame."""
        return self._state.get(self._editing_key, default=False) is True

    def _forget_commit(self) -> None:
        """Drop the commit-echo record once the Hub value has moved past it."""
        self._state.discard(self._committed_key)
        self._state.discard(self._commit_hub_key)
