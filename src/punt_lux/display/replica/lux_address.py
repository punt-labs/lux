"""LuxAddress -- the Display's own identity for one item it aggregates.

Identity is a path (system.tex Sec:addressing): each layer that aggregates
content namespaces what is below it, blind to what is above it. A
producer's own label (Rung 1) is namespaced by the Hub that owns its
connection (Rung 2, already shipped as ``ConnectionScopedId`` /
``CallbackInvocation``); the pair is namespaced, in turn, by the Hub of
origin (Rung 3), because the Display is the one layer that can see more
than one Hub. :class:`Rung` is one level of that path -- a stable key plus
a human label; :class:`LuxAddress` composes the three, outermost first.

Never round-tripped: nothing parses a LuxAddress back into its parts. It
exists only on the Display side of the wire, purely to answer "is this the
same item" (:attr:`LuxAddress.hidden_id`) and "how do I show it"
(:meth:`LuxAddress.title`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from punt_lux.domain.id_separator import ID_SEPARATOR

__all__ = ["LuxAddress", "Rung"]


@final
@dataclass(frozen=True, slots=True)
class Rung:
    """One level of a :class:`LuxAddress`: a stable uniqueness key and a label.

    ``key`` is opaque and never elided from the hidden id -- two Rungs with
    the same ``key`` are the same thing by construction. ``label`` is what a
    human reads, shown only when this rung's ambiguity requires it.
    """

    key: str
    label: str


@final
@dataclass(frozen=True, slots=True)
class LuxAddress:
    """The Display's complete identity for one item it aggregates.

    Composed of the three rungs, outermost first: the Hub of origin, the
    connection on that Hub, and the producer's own name for the item.
    """

    hub: Rung
    connection: Rung
    leaf: Rung

    @property
    def hidden_id(self) -> str:
        """The ImGui identity: every rung's key, joined, never elided."""
        return ID_SEPARATOR.join((self.hub.key, self.connection.key, self.leaf.key))

    def title(self, *, hub_ambiguous: bool, connection_ambiguous: bool) -> str:
        """The visible title: only genuinely ambiguous rungs are shown.

        The leaf is always shown; higher rungs join it, outermost first,
        only when more than one live value exists right now -- a rung's
        ambiguity is a pure cardinality question, answered by the
        :class:`~punt_lux.display.replica.address_book.AddressBook` that
        minted this address, not carried on the address itself.
        """
        shown = [
            rung.label
            for rung, ambiguous in (
                (self.hub, hub_ambiguous),
                (self.connection, connection_ambiguous),
            )
            if ambiguous
        ]
        shown.append(self.leaf.label)
        return " :: ".join(shown)
