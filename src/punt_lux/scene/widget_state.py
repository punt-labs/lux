"""Per-scene key-value store for interactive widget state across ImGui frames."""

from __future__ import annotations

from typing import Any, ClassVar, Self


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

    def set(self, element_id: str, value: Any) -> None:
        self._state[element_id] = value

    def ensure(self, element_id: str, default: Any) -> Any:
        return self._state.setdefault(element_id, default)

    def discard(self, element_id: str) -> None:
        """Remove ``element_id`` from the cache; no-op if absent."""
        self._state.pop(element_id, None)

    def discard_for(self, element_id: str) -> None:
        """Discard a removed element's key and every per-element slot beside it.

        Each key is composed from the id, never a substring match, so a survivor
        like ``btn_ok`` is never wiped. Every slot goes, for one reason: a
        re-added same-id element must start from what the Hub declares for it,
        never from what its predecessor left behind. So a dialog reopens, a tab
        bar re-honours the Hub active tab, a header shows the declared open
        state, a continuous edit honours its fresh value rather than an earlier
        commit's echo, a table its fresh selection, and a split pane its default
        proportion rather than a departed scene's dragged divider.
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

        A re-push carries the Hub's answer, so every widget that was arbitrating
        against a stale one restarts: a tab bar re-honours the Hub selection
        instead of firing a spurious ``TabChanged``, and a collapsing header
        renders the Hub's open state — which is how a toggle the Hub rejects
        pulls the display back rather than stranding it. Selection, scroll, and
        text survive.
        """
        self._state = {
            key: value
            for key, value in self._state.items()
            if not key.endswith(self._SESSION_SUFFIXES)
        }

    def clear(self) -> None:
        self._state.clear()
