"""Per-scene key-value store for interactive widget state across ImGui frames."""

from __future__ import annotations

import math
from typing import Any, ClassVar, Self, cast


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    # Suffixes of the tab-bar suppression slots (per-render-session, reset on a
    # re-push). Honoured = the active tab a frame last force-selected (echo);
    # pending = the tab a ``TabChanged`` is outstanding for (fire suppression).
    HONOURED_SUFFIX: ClassVar[str] = ":active_honoured"
    PENDING_SUFFIX: ClassVar[str] = ":active_pending"
    _SESSION_SUFFIXES: ClassVar[tuple[str, ...]] = (HONOURED_SUFFIX, PENDING_SUFFIX)

    # Suffixes of an input_text's commit-echo slots, all kept across a re-push
    # (off ``_SESSION_SUFFIXES``) so a commit in flight across the resend
    # survives. Editing = the local buffer stays authoritative mid-edit;
    # committed = the value last committed, honoured optimistically until its
    # Hub echo arrives; commit-hub = the Hub value observed at commit time, the
    # marker that tells ``resolve`` when the echo has moved past it.
    INPUT_EDITING_SUFFIX: ClassVar[str] = ":input_editing"
    INPUT_COMMITTED_SUFFIX: ClassVar[str] = ":input_committed"
    INPUT_COMMIT_HUB_SUFFIX: ClassVar[str] = ":input_commit_hub"

    # Suffixes of a slider's commit-echo slots — the numeric analog of the
    # input triple above, kept across a re-push for the same reason (a drag
    # commit may still be in flight across the resend). Editing = the live
    # thumb position stays authoritative mid-drag; committed = the value last
    # released, honoured optimistically until its Hub echo lands; commit-hub =
    # the Hub value observed at release, the marker ``resolve`` reads to tell
    # when the echo has moved past it. Distinct from the ``INPUT_*`` triple so
    # a slider and an input_text sharing neither id nor slot stay independent.
    SLIDER_EDITING_SUFFIX: ClassVar[str] = ":slider_editing"
    SLIDER_COMMITTED_SUFFIX: ClassVar[str] = ":slider_committed"
    SLIDER_COMMIT_HUB_SUFFIX: ClassVar[str] = ":slider_commit_hub"

    # Suffixes of a color_picker's commit-echo slots — the RGBA-tuple analog of
    # the triples above. Unlike ``input_text`` / ``slider`` (whose buffer lives
    # under the bare element id), the color buffer gets its OWN suffix: the
    # per-patch mirror of ``widget_value`` writes the hex *string* under the
    # bare id, so a buffer under the bare id would alias a tuple against a hex
    # string on one key. Buffer = the live RGBA tuple mid-drag; editing = that
    # tuple stays authoritative; committed = the released tuple, honoured until
    # its echo; commit-hub = the Hub tuple observed at release.
    COLOR_BUFFER_SUFFIX: ClassVar[str] = ":color_buffer"
    COLOR_EDITING_SUFFIX: ClassVar[str] = ":color_editing"
    COLOR_COMMITTED_SUFFIX: ClassVar[str] = ":color_committed"
    COLOR_COMMIT_HUB_SUFFIX: ClassVar[str] = ":color_commit_hub"

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
        re-added tab bar re-honour the Hub active tab; clearing the input,
        slider, and color-picker editing and commit-echo slots lets a re-added
        input_text, slider, or color_picker honour its fresh value instead of
        an earlier commit's optimistic echo.
        """
        if not element_id:
            return
        self.discard(element_id)
        self.discard(f"{element_id}__open")
        self.discard(f"{element_id}__dismissed")
        self.discard(f"{element_id}{self.HONOURED_SUFFIX}")
        self.discard(f"{element_id}{self.PENDING_SUFFIX}")
        self.discard(f"{element_id}{self.INPUT_EDITING_SUFFIX}")
        self.discard(f"{element_id}{self.INPUT_COMMITTED_SUFFIX}")
        self.discard(f"{element_id}{self.INPUT_COMMIT_HUB_SUFFIX}")
        self.discard(f"{element_id}{self.SLIDER_EDITING_SUFFIX}")
        self.discard(f"{element_id}{self.SLIDER_COMMITTED_SUFFIX}")
        self.discard(f"{element_id}{self.SLIDER_COMMIT_HUB_SUFFIX}")
        self.discard(f"{element_id}{self.COLOR_BUFFER_SUFFIX}")
        self.discard(f"{element_id}{self.COLOR_EDITING_SUFFIX}")
        self.discard(f"{element_id}{self.COLOR_COMMITTED_SUFFIX}")
        self.discard(f"{element_id}{self.COLOR_COMMIT_HUB_SUFFIX}")

    def reset_honoured(self) -> None:
        """Discard every tab-bar suppression slot, keeping durable user state.

        A re-push restarts each tab bar's render session, so the tab it last
        force-selected and the tab it last fired for must both be forgotten:
        the next frame re-honours the Hub selection instead of firing a spurious
        ``TabChanged`` off a stale value. Selection, scroll, and text survive.
        """
        self._state = {
            key: value
            for key, value in self._state.items()
            if not key.endswith(self._SESSION_SUFFIXES)
        }

    def clear(self) -> None:
        self._state.clear()
