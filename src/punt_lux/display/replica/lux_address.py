"""LuxAddress -- the Display's own identity for one item it aggregates.

Identity is a path (system.tex Sec:addressing): each layer that aggregates
content namespaces what is below it -- a producer's own label (Rung 1)
namespaced by the connection it arrived on (Rung 2), namespaced in turn by
the Hub of origin (Rung 3), since the Display is the one layer that can
see more than one Hub. :class:`Rung` is one level of that path; a
:class:`LuxAddress` composes the three, outermost first, purely to answer
"is this the same item" (:attr:`hidden_id`) and "how do I show it"
(:meth:`title`) -- never round-tripped back into its parts.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import compress
from typing import final

from punt_lux.domain.id_separator import ID_SEPARATOR

__all__ = ["LuxAddress", "Rung"]


@final
@dataclass(frozen=True, slots=True)
class Rung:
    """One level of a :class:`LuxAddress`: a stable uniqueness key and a label.

    ``key`` is opaque and never elided from the hidden id. ``label`` is
    what a human reads, shown only when this rung's ambiguity requires it.
    """

    key: str
    label: str


@final
@dataclass(frozen=True, slots=True)
class LuxAddress:
    """The Display's identity for one item: its three rungs, outermost first."""

    hub: Rung
    connection: Rung
    leaf: Rung

    def __post_init__(self) -> None:
        """Reject a connection/leaf key that would let :attr:`hidden_id` collide.

        The Hub rung is exempt: its key already carries the separator by
        construction (``HubId.wire_token``), unlike a caller-chosen key.
        """
        for field, rung in (("connection", self.connection), ("leaf", self.leaf)):
            if ID_SEPARATOR in rung.key:
                msg = f"{field} key must not contain the unit separator"
                raise ValueError(msg)

    @property
    def hidden_id(self) -> str:
        """The ImGui identity: every rung's key, joined, never elided."""
        return ID_SEPARATOR.join((self.hub.key, self.connection.key, self.leaf.key))

    def title(self, *, hub_ambiguous: bool, connection_ambiguous: bool) -> str:
        """The visible title: only genuinely ambiguous rungs are shown.

        The leaf is always shown; higher rungs join it, outermost first,
        only when their ambiguity -- a caller-answered cardinality question,
        not carried on the address itself -- says to.
        """
        shown = list(
            compress(
                (self.hub.label, self.connection.label),
                (hub_ambiguous, connection_ambiguous),
            )
        )
        shown.append(self.leaf.label)
        return " :: ".join(shown)
