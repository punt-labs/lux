"""What a write to a connection's listener slot did — the registry's two verdicts.

One connection is shared by successive sessions of one identity, so a write to
its slot is never simply "done": it either won the compare against the session
occupying the slot or it did not, and the caller's next move depends on which.
These are the names for those outcomes.

They live apart from the registry that returns them so a caller can name an
outcome without importing the store — the operations layer maps a registration
verdict to its reply, and the listen leg maps a detachment to whether the menu
bar must be re-pushed.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["CallbackRegistration", "ListenerAttachment", "ListenerDetachment"]

# What taking the slot did to the entries already in it. A connection that had
# none is ``attached``; one whose previous occupant still owned entries is
# ``attached_over_callbacks``, and those entries have just stopped being
# deliverable — the caller's cue to re-push the bar.
ListenerAttachment = Literal["attached", "attached_over_callbacks"]

# What a registration did. ``superseded`` is the compare-and-set losing: the leg
# the caller was gated against is no longer the connection's, so the entry would be
# one nothing could ever deliver a click to. ``declined`` is the session refusing —
# it is anonymous, or its lease has lapsed — and declaring an identity answers both,
# since identifying is itself a renewal.
CallbackRegistration = Literal["registered", "superseded", "declined"]

# What a teardown found the connection's slot to be. Exactly one outcome is a
# keep, and the distinction that matters is what the bar is showing afterwards.
#
#   kept                      a successor holds the slot; its entries are live and
#                             the bar is right, so nothing here may be removed.
#   released                  this session held the slot and owned no entries.
#   released_with_callbacks   this session held the slot, and its entries went
#                             with it.
#   released_with_session     the lease lapsed and the sweep took the whole
#                             session — slot, entries, and all — while this socket
#                             was still winding down. Nobody holds the connection,
#                             so this is a release like the two above and not a
#                             keep: reading it as one leaves the bar showing
#                             entries with no owner left.
#
# Every outcome but ``kept`` and bare ``released`` is the caller's cue to re-push
# the bar. None of them decides what happens to the session's own Hub-side state,
# which is released by identity on every path.
ListenerDetachment = Literal[
    "kept", "released", "released_with_callbacks", "released_with_session"
]
