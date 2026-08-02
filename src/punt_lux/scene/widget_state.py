"""Per-scene key-value store for interactive widget state across ImGui frames."""

from __future__ import annotations

import math
from typing import Any, ClassVar, Self, cast


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    # Suffixes of a modal/dialog's open/dismiss latch slots — the single source
    # every producer (the ImGui modal and dialog adapters, the legacy modal
    # renderer) and the ``discard_for`` consumer share, so a re-added same-id
    # popup reopens only while these keys agree. Kept across a re-push.
    OPEN_SUFFIX: ClassVar[str] = "__open"
    DISMISS_SUFFIX: ClassVar[str] = "__dismissed"

    # Suffixes of the per-render-session slots, reset on a re-push because that
    # push carries the Hub's answer and supersedes whatever the display was
    # holding. Honoured = the active tab a frame last force-selected (echo);
    # pending = the tab a ``TabChanged`` is outstanding for (fire suppression);
    # header-open = the open state a ``HeaderToggled`` is outstanding for, so the
    # frames before the Hub answers render the user's toggle instead of the
    # not-yet-updated Hub value.
    HONOURED_SUFFIX: ClassVar[str] = ":active_honoured"
    PENDING_SUFFIX: ClassVar[str] = ":active_pending"
    HEADER_OPEN_PENDING_SUFFIX: ClassVar[str] = ":header_open_pending"
    _SESSION_SUFFIXES: ClassVar[tuple[str, ...]] = (
        HONOURED_SUFFIX,
        PENDING_SUFFIX,
        HEADER_OPEN_PENDING_SUFFIX,
    )

    # Suffixes of a continuous-edit widget's commit-echo slots, shared by every
    # non-atomic mutable kind (input_text, slider, color_picker) and kept across a
    # re-push so a commit in flight survives. Buffer = the live local edit,
    # authoritative while editing; editing = the flag marking that authority;
    # committed = the value honoured optimistically until its Hub echo arrives;
    # commit-hub = the Hub value at commit time, telling ``resolve`` when the echo
    # moved past it. Unique element ids keep the one quad from colliding across
    # widgets; the buffer takes its own suffix so it never aliases the bare id.
    CONTINUOUS_EDIT_BUFFER_SUFFIX: ClassVar[str] = ":continuous_edit_buffer"
    CONTINUOUS_EDIT_EDITING_SUFFIX: ClassVar[str] = ":continuous_edit_editing"
    CONTINUOUS_EDIT_COMMITTED_SUFFIX: ClassVar[str] = ":continuous_edit_committed"
    CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX: ClassVar[str] = ":continuous_edit_commit_hub"

    # Suffixes of a table's row-selection bridge slots, owned by the display's
    # ``TableSelectionArbiter`` and durable across a re-push so a gesture in flight
    # survives: pending = the fired set held optimistically through the
    # gesture-to-re-push window, so a second gesture accumulates on the first;
    # honoured = the authoritative set observed last frame, telling the arbiter
    # when the Hub value moved on and the pending must yield to it.
    ROW_SELECTION_PENDING_SUFFIX: ClassVar[str] = ":row_selection_pending"
    ROW_SELECTION_HONOURED_SUFFIX: ClassVar[str] = ":row_selection_honoured"

    # Suffixes of an autofocus input's keyboard-focus slots, owned by the display's
    # ``SearchFocusArbiter``. Durable across a re-push (off ``_SESSION_SUFFIXES``) so
    # a scene the poller replaces every few seconds keeps focus where the user left
    # it: seen = the scene has focused this input once (focus-once at first arrival,
    # never re-stolen on a resend); refocus = a return-to-focus armed by the input's
    # own enter-commit, consumed the next frame.
    FOCUS_SEEN_SUFFIX: ClassVar[str] = ":focus_seen"
    FOCUS_REFOCUS_SUFFIX: ClassVar[str] = ":focus_refocus"

    # Suffix of a split pane's grid/detail divider ratio, owned by the display's
    # ``SplitRatioStore``. Durable across a re-push so a dragged divider survives
    # the poller replacing a scene: the ratio is the top pane's height fraction,
    # applied locally with no Hub round-trip on drag.
    SPLIT_RATIO_SUFFIX: ClassVar[str] = ":split_ratio"

    _state: dict[str, Any]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._state = {}
        return self

    def get(self, element_id: str, default: Any = None) -> Any:
        return self._state.get(element_id, default)

    def get_str(self, element_id: str) -> str:
        """Return the stored string, or ``""`` when absent or non-str."""
        value = self._state.get(element_id)
        return value if isinstance(value, str) else ""

    def get_float(self, element_id: str, default: float) -> float:
        """Return the stored number as ``float``, or ``default`` when absent.

        The numeric analog of ``get_str``: a slider buffer has no empty
        sentinel, so a miss falls back to the caller-supplied default (the
        current Hub value or ``min``) rather than a magic ``""``. A stored
        ``bool`` is not a slider value, so it reads as the default too.
        """
        value = self._state.get(element_id)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return default
        return float(value)

    def get_tuple(
        self,
        element_id: str,
        default: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        """Return the stored RGBA tuple normalized to arity 4, or ``default``.

        The color analog of ``get_float``: the buffer holds an RGBA tuple, so a
        miss falls back to the caller-supplied default (the current Hub color).
        A stored value that is not a length-3/4 tuple of finite ``float`` reads
        as the default too. The return is always arity 4 — a length-3 stored
        tuple pads its alpha to opaque — because ``resolve``'s editing branch
        returns this buffer uncoerced and tuple equality needs a fixed arity.
        """
        coerced = self._as_rgba4(self._state.get(element_id))
        return coerced if coerced is not None else default

    @staticmethod
    def _as_rgba4(value: object) -> tuple[float, float, float, float] | None:
        # PY-TS-14 OK: ``None`` is the internal "not a valid RGBA tuple" signal
        # get_tuple maps to its default — it never escapes to a caller.
        if not isinstance(value, tuple):
            return None
        comps = cast("tuple[object, ...]", value)
        if len(comps) not in (3, 4):
            return None
        floats: list[float] = []
        for c in comps:
            if isinstance(c, bool) or not isinstance(c, int | float):
                return None
            if not math.isfinite(c):
                return None
            floats.append(float(c))
        if len(floats) == 3:
            floats.append(1.0)
        return (floats[0], floats[1], floats[2], floats[3])

    def set(self, element_id: str, value: Any) -> None:
        self._state[element_id] = value

    def ensure(self, element_id: str, default: Any) -> Any:
        return self._state.setdefault(element_id, default)

    def discard(self, element_id: str) -> None:
        """Remove ``element_id`` from the cache; no-op if absent."""
        self._state.pop(element_id, None)

    def discard_for(self, element_id: str) -> None:
        """Discard a removed element's key, dialog latches, and interactive slots.

        Each key is built from the id, never a substring match, so a survivor
        like ``btn_ok`` is never wiped. Clearing the dialog latches lets a
        re-added same-id dialog reopen; clearing the tab-bar slots lets a
        re-added tab bar re-honour the Hub active tab; clearing the header's
        optimistic open flag lets a re-added collapsing header show the Hub's
        declared state instead of a departed header's in-flight toggle; clearing
        the shared continuous-edit buffer and commit-echo quad lets a re-added
        input_text, slider, or color_picker honour its fresh value instead of an
        earlier commit's optimistic echo; clearing the table selection bridge lets a
        re-added table honour its fresh selection instead of a stale pending set;
        clearing the split ratio lets a re-added split pane honour its fresh
        default proportion instead of a departed scene's dragged divider.
        """
        if not element_id:
            return
        self.discard(element_id)
        self.discard(f"{element_id}{self.OPEN_SUFFIX}")
        self.discard(f"{element_id}{self.DISMISS_SUFFIX}")
        self.discard(f"{element_id}{self.HONOURED_SUFFIX}")
        self.discard(f"{element_id}{self.PENDING_SUFFIX}")
        self.discard(f"{element_id}{self.HEADER_OPEN_PENDING_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_BUFFER_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_EDITING_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_COMMITTED_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}")
        self.discard(f"{element_id}{self.ROW_SELECTION_PENDING_SUFFIX}")
        self.discard(f"{element_id}{self.ROW_SELECTION_HONOURED_SUFFIX}")
        self.discard(f"{element_id}{self.FOCUS_SEEN_SUFFIX}")
        self.discard(f"{element_id}{self.FOCUS_REFOCUS_SUFFIX}")
        self.discard(f"{element_id}{self.SPLIT_RATIO_SUFFIX}")

    def reset_session_slots(self) -> None:
        """Discard every per-render-session slot, keeping durable user state.

        A re-push carries the Hub's current answer, so it restarts the render
        session of every widget that was arbitrating against a stale one. A tab
        bar forgets the tab it last force-selected and the tab it last fired
        for, so the next frame re-honours the Hub selection instead of firing a
        spurious ``TabChanged``. A collapsing header forgets the open state it
        was optimistically showing, so the next frame renders the Hub's value —
        which is how a toggle the Hub rejects pulls the display back rather than
        stranding it. Selection, scroll, and text survive.
        """
        self._state = {
            key: value
            for key, value in self._state.items()
            if not key.endswith(self._SESSION_SUFFIXES)
        }

    def clear(self) -> None:
        self._state.clear()
