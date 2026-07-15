"""The color_picker drag/commit arbiter — the honour-or-defer decision, imgui-free.

A ``color_picker`` carries one Hub-authoritative ``value`` (a hex color string),
but while the user drags a sub-control — the saturation-value square, the hue or
alpha bar, an RGB input — the *local color* is authoritative. The arbiter encodes
the controlled-input-over-latency rule so the honour-vs-keep-dragging decision is
testable without ImGui.

Idle: the rendered color is ``elem.value`` (parsed to a tuple) each frame, so an
agent-driven change appears next frame (checkbox-style). Dragging: the buffer
tuple is authoritative and a Hub-driven value is ignored, so a Hub re-push
landing mid-drag cannot clobber the color under the user's cursor. Deferring
begins only on the first genuine drag ``observe`` sees, not on mere grab, so an
echo arriving mid-grab still reaches an ungrabbed control. Exactly one
``ValueChanged`` fires on release (deactivate-after-edit), never per drag frame —
and the color_edit/color_picker sub-controls each fire their own independent
deactivate, so a single gesture across several sub-controls commits the whole
color once per sub-control release, always as a hex string.

The Hub and Display are separate processes, so a committed value returns as
``elem.value`` only after an echo-latency window. Through that window ``resolve``
honours the committed tuple locally — the optimistic echo — so a re-grab or drag
in it builds on it; see ``resolve`` for the rule and its limits.

This is the RGBA-tuple sibling of ``SliderArbiter``: same four slots, same
honour/defer/commit/echo control flow. Only the carried value's type differs (an
arity-4 ``tuple[float, ...]`` read through ``WidgetState.get_tuple``), and — unlike
``slider`` — the buffer lives under its own ``COLOR_BUFFER`` suffix rather than
the bare element id, so the tuple buffer never aliases the per-patch hex-string
mirror on one key.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.protocol.elements.rgba_color import Rgba, RgbaColor
from punt_lux.scene.widget_state import WidgetState

__all__ = ["ColorPickerArbiter"]


@final
class ColorPickerArbiter:
    """Resolve a color picker's rendered color under the commit-echo rule."""

    _state: WidgetState
    _buffer_key: str
    _editing_key: str
    _committed_key: str
    _commit_hub_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._buffer_key = f"{element_id}{WidgetState.COLOR_BUFFER_SUFFIX}"
        self._editing_key = f"{element_id}{WidgetState.COLOR_EDITING_SUFFIX}"
        self._committed_key = f"{element_id}{WidgetState.COLOR_COMMITTED_SUFFIX}"
        self._commit_hub_key = f"{element_id}{WidgetState.COLOR_COMMIT_HUB_SUFFIX}"
        return self

    def resolve(self, hub_value: Rgba) -> Rgba:
        """Return the RGBA color ImGui renders this frame.

        While dragging, the buffer wins (protecting the live color). Otherwise,
        if a committed color is recorded and the Hub color still matches the
        color observed at commit time, honour the committed color — the
        optimistic echo through the latency window. Once the Hub color has moved,
        forget the commit and honour the Hub.

        Reconciliation is by value equality alone: a commit carries no echo
        token, and one committed/commit-hub pair holds only the latest commit.
        Tuple ``==`` is elementwise, so the window closes atomically only when
        *every* channel echoes back. ``ColorPickerElement.validate`` rejects a
        malformed hex, and a well-formed hex parses to finite channels, so
        ``hub_value == commit_hub`` stays reflexive (no ``NaN`` channel).

        Two non-data-loss limits follow from the single-slot design, each
        needing timing inside one echo round-trip (negligible on localhost): two
        commits within a round-trip can transiently revert the display to the
        intermediate Hub color (a flicker — the second commit's echo still
        lands); and an agent driving the Hub back to the exact commit-time color
        in the window is masked as the pending echo until the color next moves
        off it (even less reachable than for a scalar — all four channels must
        match bit-for-bit).
        """
        if self._editing:
            return self._state.get_tuple(self._buffer_key, default=hub_value)
        committed = self._state.get(self._committed_key)
        if committed is not None and hub_value == self._state.get(self._commit_hub_key):
            return RgbaColor.coerce(committed)
        self._forget_commit()
        return hub_value

    def observe(self, *, edited: bool, value: Rgba) -> None:
        """Record ``value`` as the buffer and begin deferring — only on a real drag.

        A genuine drag frame (or a control already being dragged) is
        authoritative over its buffer; a grabbed-but-not-yet-moved frame is left
        honouring so an echo can still reach it.
        """
        if edited or self._editing:
            self._state.set(self._editing_key, value=True)
            self._state.set(self._buffer_key, value)

    def commit(self, value: Rgba, hub_value: Rgba) -> None:
        """Record the committed color and the Hub color observed at commit time.

        Opens the optimistic-echo window ``resolve`` honours until the Hub color
        moves off ``hub_value``. The value recorded is the quantized (8-bit
        round-tripped) tuple, so it bit-equals the eventual echo and closes the
        window with no full-precision→8-bit color pop. The editing flag is left
        for ``release`` to clear.
        """
        self._state.set(self._committed_key, value)
        self._state.set(self._commit_hub_key, hub_value)

    def release(self) -> None:
        """Mark the picker idle and drop the buffer, keeping the commit-echo record.

        The committed color stays honoured until ``resolve`` sees the Hub color
        move past the commit-time color; only then is it forgotten.
        """
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)

    @property
    def _editing(self) -> bool:
        """Return whether a sub-control was being dragged as of the last frame."""
        return self._state.get(self._editing_key, default=False) is True

    def _forget_commit(self) -> None:
        """Drop the commit-echo record once the Hub color has moved past it."""
        self._state.discard(self._committed_key)
        self._state.discard(self._commit_hub_key)
