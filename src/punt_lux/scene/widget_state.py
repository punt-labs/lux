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

    # Suffixes of a continuous-edit widget's commit-echo slots, shared by every
    # non-atomic mutable kind (input_text, slider, color_picker) — all kept
    # across a re-push (off ``_SESSION_SUFFIXES``) so a commit in flight across
    # the resend survives. Buffer = the live local edit (text, thumb position,
    # or RGBA tuple) that stays authoritative while the widget is being edited;
    # editing = the flag that marks that authority; committed = the value last
    # committed, honoured optimistically until its Hub echo arrives; commit-hub =
    # the Hub value observed at commit time, the marker that tells ``resolve``
    # when the echo has moved past it. One neutral quad serves all three: element
    # ids are unique within a scene and the arbiter is the sole reader/writer of
    # these slots, so no two widgets collide, and the type-guarding getters map a
    # wrong-typed stored value to their default. The buffer takes its own suffix
    # (never the bare id) so it can never alias a per-patch hex-string mirror of
    # ``widget_value`` on one key, for any kind uniformly.
    CONTINUOUS_EDIT_BUFFER_SUFFIX: ClassVar[str] = ":continuous_edit_buffer"
    CONTINUOUS_EDIT_EDITING_SUFFIX: ClassVar[str] = ":continuous_edit_editing"
    CONTINUOUS_EDIT_COMMITTED_SUFFIX: ClassVar[str] = ":continuous_edit_committed"
    CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX: ClassVar[str] = ":continuous_edit_commit_hub"

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
        re-added tab bar re-honour the Hub active tab; clearing the shared
        continuous-edit buffer and commit-echo quad lets a re-added input_text,
        slider, or color_picker honour its fresh value instead of an earlier
        commit's optimistic echo.
        """
        if not element_id:
            return
        self.discard(element_id)
        self.discard(f"{element_id}__open")
        self.discard(f"{element_id}__dismissed")
        self.discard(f"{element_id}{self.HONOURED_SUFFIX}")
        self.discard(f"{element_id}{self.PENDING_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_BUFFER_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_EDITING_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_COMMITTED_SUFFIX}")
        self.discard(f"{element_id}{self.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}")

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
