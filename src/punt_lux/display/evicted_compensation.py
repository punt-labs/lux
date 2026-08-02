"""What an evicted interaction owes the display — the optimism it must give up.

An interaction the display's pending buffer evicts — aged out, or pushed past the
count cap — never reaches the Hub, so no answer for it will ever arrive. Any state
the display latched when it fired would then render forever against an unchanged
Hub: a modal held shut, a table row held selected, a header held open. Eviction is
behaviourally a rejection that never got said, and the reconciliation models give
a rejection one meaning — clear the optimistic slot, and the next frame renders
the Hub's value (``docs/header_toggle_reconciliation.tex``, invariants 4 and 5:
the pending value is held only while a gesture is outstanding, and once no gesture
is outstanding what is shown is the Hub's).

Each interaction kind that latches display-side state names its slots in one
``SlotCompensation``. A kind that latches nothing — a button click, whose whole
effect is Hub-side — takes ``NullCompensation`` and does nothing.
``CompensationTable`` maps the wire ``event_kind`` to the right one, so the
compensating leg reads a value rather than branching on a tag, and a new
interactive kind is one more entry rather than one more branch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Protocol, Self, final, runtime_checkable

from punt_lux.scene import WidgetState

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "Compensation",
    "CompensationTable",
    "NullCompensation",
    "SlotCompensation",
]


@runtime_checkable
class Compensation(Protocol):
    """What one interaction kind owes the widget state it latched.

    The parameters are positional-only so an implementation that needs neither
    is free to name them as the unused arguments they are.
    """

    def revert(self, ws: WidgetState, element_id: str, /) -> None:
        """Give up the optimism the lost interaction was speaking for."""
        ...


@final
class NullCompensation:
    """The compensation of a kind that latches nothing (PY-DP-9 Null Object)."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def revert(self, _ws: WidgetState, _element_id: str, /) -> None:
        """Do nothing — this kind left no display-side state to unwind."""


@final
class SlotCompensation:
    """The widget-state slots one interaction kind holds optimistically."""

    _what: str
    _suffixes: tuple[str, ...]
    __slots__ = ("_suffixes", "_what")

    def __new__(cls, what: str, /, *suffixes: str) -> Self:
        self = super().__new__(cls)
        self._what = what
        self._suffixes = suffixes
        return self

    def revert(self, ws: WidgetState, element_id: str, /) -> None:
        """Discard every slot this kind latches, handing the element back to the Hub.

        Discarding is unconditional: a slot the widget never wrote is already in
        the state this leaves it in, and the widget reads its absence as nothing
        pending — the Hub's value.
        """
        for suffix in self._suffixes:
            ws.discard(f"{element_id}{suffix}")
        logger.warning(
            "cleared %s for '%s' — the interaction never reached the Hub",
            self._what,
            element_id,
        )


@final
class CompensationTable:
    """What each interaction kind owes when its interaction is lost."""

    # Keyed by the wire ``event_kind``. An invocation carries none for a kind
    # that declared none, and a kind that latches nothing is simply absent; both
    # miss and take the null compensation, which is why the key type admits None.
    _BY_KIND: ClassVar[Mapping[str | None, Compensation]] = {
        "modal_closed": SlotCompensation(
            "a modal's dismiss",
            WidgetState.OPEN_SUFFIX,
            WidgetState.DISMISS_SUFFIX,
        ),
        "row_selection_changed": SlotCompensation(
            "a table's pending selection",
            WidgetState.ROW_SELECTION_PENDING_SUFFIX,
            WidgetState.ROW_SELECTION_HONOURED_SUFFIX,
        ),
        "header_toggled": SlotCompensation(
            "a header's pending toggle",
            WidgetState.HEADER_OPEN_PENDING_SUFFIX,
        ),
        "tab_changed": SlotCompensation(
            "a tab bar's pending switch",
            WidgetState.PENDING_SUFFIX,
            WidgetState.HONOURED_SUFFIX,
        ),
        # Only the commit-echo pair: the buffer and its editing flag are the
        # user's live keystrokes, not optimism about the Hub, and a commit lost
        # in flight must not wipe what is being typed now.
        "value_changed": SlotCompensation(
            "an edit's committed value",
            WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX,
            WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX,
        ),
    }
    _NOTHING_LATCHED: ClassVar[Compensation] = NullCompensation()

    @classmethod
    def for_kind(cls, event_kind: str | None) -> Compensation:
        """Return what an evicted ``event_kind`` owes the display's replica."""
        return cls._BY_KIND.get(event_kind, cls._NOTHING_LATCHED)
