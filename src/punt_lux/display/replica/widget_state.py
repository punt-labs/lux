"""Per-scene key-value store for interactive widget state across ImGui frames."""

from __future__ import annotations

from typing import Any, ClassVar, Self, cast

# The wire-safe shape a curated value reduces to (declared here, not imported
# from the Hub-side ``operations`` package the Display never depends on) --
# ``tuple[float, ...]`` is a color picker's RGBA slot (RgbaColor.as_tuple).
# Mirrors operations/models/display_state.py's WireScalar; widen both together.
type WireScalar = str | float | bool | tuple[str, ...] | tuple[float, ...]


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    # A modal/dialog's open/dismiss latch, shared by every producer and by
    # ``discard_for``. Kept across a re-push.
    OPEN_SUFFIX: ClassVar[str] = "__open"
    DISMISS_SUFFIX: ClassVar[str] = "__dismissed"

    # Per-render-session slots, reset on a re-push. Honoured = the tab/header
    # state last force-selected (echo); pending = the change outstanding.
    HONOURED_SUFFIX: ClassVar[str] = ":active_honoured"
    PENDING_SUFFIX: ClassVar[str] = ":active_pending"
    HEADER_OPEN_PENDING_SUFFIX: ClassVar[str] = ":header_open_pending"
    _SESSION_SUFFIXES: ClassVar[tuple[str, ...]] = (
        HONOURED_SUFFIX,
        PENDING_SUFFIX,
        HEADER_OPEN_PENDING_SUFFIX,
    )

    # A continuous-edit widget's commit-echo quad, kept across a re-push.
    # Buffer/editing = the live local edit and its flag; committed/commit-hub
    # = the value honoured optimistically until the Hub's echo arrives.
    CONTINUOUS_EDIT_BUFFER_SUFFIX: ClassVar[str] = ":continuous_edit_buffer"
    CONTINUOUS_EDIT_EDITING_SUFFIX: ClassVar[str] = ":continuous_edit_editing"
    CONTINUOUS_EDIT_COMMITTED_SUFFIX: ClassVar[str] = ":continuous_edit_committed"
    CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX: ClassVar[str] = ":continuous_edit_commit_hub"

    # A table's row-selection bridge (``TableSelectionArbiter``). Pending =
    # fired, held through the gesture-to-re-push window; honoured = confirmed.
    ROW_SELECTION_PENDING_SUFFIX: ClassVar[str] = ":row_selection_pending"
    ROW_SELECTION_HONOURED_SUFFIX: ClassVar[str] = ":row_selection_honoured"

    # An autofocus input's keyboard-focus slots (``SearchFocusArbiter``).
    # Seen = focused once already; refocus = armed by the enter-commit.
    FOCUS_SEEN_SUFFIX: ClassVar[str] = ":focus_seen"
    FOCUS_REFOCUS_SUFFIX: ClassVar[str] = ":focus_refocus"

    # A split pane's grid/detail divider ratio (``SplitRatioStore``), applied
    # locally with no Hub round-trip on drag.
    SPLIT_RATIO_SUFFIX: ClassVar[str] = ":split_ratio"

    # True only for the width of one in-flight click -- excluded from
    # ``observable_snapshot``.
    _GESTURE_SUFFIXES: ClassVar[tuple[str, ...]] = (
        OPEN_SUFFIX,
        DISMISS_SUFFIX,
        PENDING_SUFFIX,
        HEADER_OPEN_PENDING_SUFFIX,
        CONTINUOUS_EDIT_BUFFER_SUFFIX,
        CONTINUOUS_EDIT_EDITING_SUFFIX,
        ROW_SELECTION_PENDING_SUFFIX,
        FOCUS_REFOCUS_SUFFIX,  # one-frame transient, armed by the enter-commit
    )
    # Every per-element suffix -- what ``discard_for`` sweeps.
    _ALL_SUFFIXES: ClassVar[tuple[str, ...]] = (
        *_GESTURE_SUFFIXES,
        HONOURED_SUFFIX,
        CONTINUOUS_EDIT_COMMITTED_SUFFIX,
        CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX,
        ROW_SELECTION_HONOURED_SUFFIX,
        FOCUS_SEEN_SUFFIX,
        SPLIT_RATIO_SUFFIX,
    )

    _state: dict[str, Any]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._state = {}
        return self

    def get(self, element_id: str, default: Any = None) -> Any:
        return self._state.get(element_id, default)

    # The typed reads reject rather than coerce a slot of the wrong type.
    # Text has an empty sentinel; a number/flag take the caller's default.
    def get_str(self, element_id: str) -> str:
        """Return the stored string, or ``""`` when absent or non-str."""
        value = self._state.get(element_id)
        return value if isinstance(value, str) else ""

    def get_float(self, element_id: str, default: float) -> float:
        """Return the stored number as ``float``, or ``default`` — a flag is a miss."""
        value = self._state.get(element_id)
        return (
            float(value)
            if isinstance(value, int | float) and not isinstance(value, bool)
            else default
        )

    def get_bool(self, element_id: str, *, default: bool) -> bool:
        """Return the stored flag, or ``default`` when absent or non-bool."""
        value = self._state.get(element_id)
        return value if isinstance(value, bool) else default

    def set(self, element_id: str, value: Any) -> None:
        self._state[element_id] = value

    def discard(self, element_id: str) -> None:
        """Remove ``element_id`` from the cache; no-op if absent."""
        self._state.pop(element_id, None)

    def discard_for(self, element_id: str) -> None:
        """Discard a removed element's key and every per-element slot beside it."""
        if not element_id:
            return
        self.discard(element_id)
        for suffix in self._ALL_SUFFIXES:
            self.discard(f"{element_id}{suffix}")

    def reset_session_slots(self) -> None:
        """Discard every per-render-session slot; durable user state survives."""
        self._state = {
            key: value
            for key, value in self._state.items()
            if not key.endswith(self._SESSION_SUFFIXES)
        }

    def clear(self) -> None:
        self._state.clear()

    def observable_snapshot(self) -> dict[str, WireScalar]:
        """Return steady-state values; every gesture-window slot is excluded."""
        observable = filter(lambda kv: self._is_observable(kv[0]), self._state.items())
        return {key: self._wire_value(value) for key, value in observable}

    @classmethod
    def _is_observable(cls, key: str) -> bool:
        return not key.endswith(cls._GESTURE_SUFFIXES)

    @staticmethod
    def _wire_value(value: Any) -> WireScalar:
        """Narrow a stored value to its wire-safe shape.

        The row-selection slot is the one ``frozenset``, sorted to a tuple;
        every other shape (a color picker's RGBA tuple included) passes through.
        """
        return (
            tuple(sorted(cast("frozenset[str]", value)))
            if isinstance(value, frozenset)
            else cast("WireScalar", value)
        )
