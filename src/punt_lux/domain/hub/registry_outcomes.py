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

__all__ = ["CallbackRegistration", "ListenerDetachment"]

# What a registration did. ``superseded`` is the compare-and-set losing: the leg
# the caller was gated against is no longer the connection's, so the entry would be
# one nothing could ever deliver a click to. ``declined`` is the session refusing —
# it is anonymous, or its lease has lapsed — and declaring an identity answers both,
# since identifying is itself a renewal.
CallbackRegistration = Literal["registered", "superseded", "declined"]

# What a teardown did to the connection's slot. ``kept`` is the stale case: a
# successor holds the slot, so nothing was removed and the bar still shows entries
# that are live. ``session_gone`` is the lapsed case: the sweep took the session,
# its slot and its entries with it, while this socket was still winding down. The
# other two released the slot here, differing only in whether menu items went with
# it. Every outcome but ``kept`` is the caller's cue to re-push the bar.
ListenerDetachment = Literal[
    "kept", "session_gone", "released", "released_with_callbacks"
]
