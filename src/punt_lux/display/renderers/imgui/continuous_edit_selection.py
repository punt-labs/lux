# pyright: reportUnknownMemberType=false
"""The shared continuous-edit arbiter — the honour-or-defer decision, imgui-free.

A non-atomic mutable widget (``input_text``, ``slider``, ``color_picker``)
carries one Hub-authoritative ``value``, but while the user edits, the *local
buffer* — not the Hub value — is authoritative. This arbiter encodes the
controlled-input-over-latency rule (how form libraries handle a slow round
trip) so the honour-vs-keep-editing decision is testable without ImGui.

Idle: the rendered value is ``elem.value`` each frame, so an agent-driven
change appears next frame (checkbox-style). Editing: the buffer is
authoritative and a Hub-driven ``value`` is ignored, so two edits in flight
before a round trip returns cannot clobber the live edit. Deferring begins only
on the first genuine edit ``observe`` sees, not on mere focus, so an echo
arriving mid-focus still reaches an unedited widget. Exactly one
``ValueChanged`` fires on commit (blur, Enter, or release), never per frame.

The Hub and Display are separate processes, so a committed value returns as
``elem.value`` only after an echo-latency window. Through that window
``resolve`` honours the committed value locally — the optimistic echo — so a
re-focus or edit in it builds on it; see ``resolve`` for the rule and limits.

The four slots (buffer, editing, committed, commit-hub) and the whole
honour/defer/commit/echo control flow are carrier-agnostic: they use only the
untyped ``WidgetState`` accessors and Python ``==``. The two carrier-typed
touches — the buffer read (with its per-type miss policy) and the committed
coercion — are delegated to an injected ``ValueAccessor[T]``. Governed by
``docs/input_text_reconciliation.tex``.
"""

from __future__ import annotations

from typing import Protocol, Self, final, runtime_checkable

from punt_lux.scene.widget_state import WidgetState

__all__ = ["ContinuousEditArbiter", "ValueAccessor"]


@runtime_checkable
class ValueAccessor[T](Protocol):
    """The two carrier-typed touches a ContinuousEditArbiter delegates.

    Everything else in the arbiter — the four state slots, the honour/defer/
    commit/echo control flow, value-equality reconciliation — is carrier-
    agnostic. Only the buffer read (with its per-type miss policy) and the
    committed-value coercion carry the type.
    """

    def read(self, state: WidgetState, key: str, hub_value: T) -> T:
        """Return the live buffer this frame; the miss policy is per-type.

        ``input_text`` returns ``""`` on a miss (a real cleared-field state,
        ignoring ``hub_value``); ``slider`` and ``color_picker`` fall back to
        ``hub_value``.
        """
        ...

    def coerce(self, stored: object) -> T:
        """Coerce a stored committed value to the carrier type for return."""
        ...


@final
class ContinuousEditArbiter[T]:
    """Resolve a non-atomic mutable widget's value under the commit-echo rule."""

    _state: WidgetState
    _accessor: ValueAccessor[T]
    _buffer_key: str
    _editing_key: str
    _committed_key: str
    _commit_hub_key: str

    def __new__(
        cls, state: WidgetState, element_id: str, accessor: ValueAccessor[T]
    ) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._accessor = accessor
        self._buffer_key = f"{element_id}{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}"
        self._editing_key = f"{element_id}{WidgetState.CONTINUOUS_EDIT_EDITING_SUFFIX}"
        self._committed_key = (
            f"{element_id}{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}"
        )
        self._commit_hub_key = (
            f"{element_id}{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}"
        )
        return self

    def resolve(self, hub_value: T) -> T:
        """Return the value ImGui renders this frame.

        While editing, the buffer wins (protecting the live edit). Otherwise, if
        a committed value is recorded and the Hub value still matches the value
        observed at commit time, honour the committed value — the optimistic
        echo through the latency window. Once the Hub value has moved, forget the
        commit and honour the Hub.

        Reconciliation is by value equality alone — a commit carries no echo
        token or version, and one committed/commit-hub pair holds only the latest
        commit. Value equality assumes ``x == x`` is reflexive; a ``NaN`` carrier
        would never compare equal to its commit-hub marker, so it would take the
        forget branch and snap to the raw Hub. Each element's ``validate`` keeps
        the carrier finite (the slider by a ``math.isfinite`` guard, the color by
        the hex encoding, the text trivially), so the window closes as intended.

        Two non-data-loss limits follow from the single-slot design, each needing
        timing inside one echo round-trip (negligible on localhost): two commits
        within a round-trip can transiently revert the display to the
        intermediate Hub value (a flicker — the second commit's echo still
        lands); and an agent driving the Hub back to the exact commit-time value
        in the window is masked as the pending echo until the value next moves off
        it.
        """
        if self._editing:
            return self._accessor.read(self._state, self._buffer_key, hub_value)
        committed = self._state.get(self._committed_key)
        if committed is not None and hub_value == self._state.get(self._commit_hub_key):
            return self._accessor.coerce(committed)
        self._forget_commit()
        return hub_value

    def observe(self, *, edited: bool, value: T) -> None:
        """Record ``value`` as the buffer and begin deferring — but only on a real edit.

        A genuine edit (or a widget already editing) is authoritative over its
        buffer; a focused-but-not-yet-edited frame is left honouring so an echo
        can still reach it.
        """
        if edited or self._editing:
            self._state.set(self._editing_key, value=True)
            self._state.set(self._buffer_key, value)

    def commit(self, value: T, hub_value: T) -> None:
        """Record the committed value and the Hub value observed at commit time.

        Opens the optimistic-echo window ``resolve`` honours until the Hub value
        moves off ``hub_value``. The editing flag is left for ``release`` to clear.
        """
        self._state.set(self._committed_key, value)
        self._state.set(self._commit_hub_key, hub_value)

    def release(self) -> None:
        """Mark the widget idle and drop the buffer, keeping the commit-echo record.

        The committed value stays honoured until ``resolve`` sees the Hub value
        move past the commit-time value; only then is it forgotten.
        """
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)

    @property
    def _editing(self) -> bool:
        """Return whether the widget was being edited as of the last frame."""
        return self._state.get(self._editing_key, default=False) is True

    def _forget_commit(self) -> None:
        """Drop the commit-echo record once the Hub value has moved past it."""
        self._state.discard(self._committed_key)
        self._state.discard(self._commit_hub_key)
