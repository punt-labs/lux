"""FrameOwnership -- what the Hub knows about a frame's owner, as one value.

A frame's canonical owner answers two questions the Display shows: the rows of
the ``i`` popup and the connection-scope label that prefixes the frame's title
(DES-100). Both come from the same owner in the same read, so they travel as
one value and can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

__all__ = ["UNOWNED", "FrameOwnership"]


@final
@dataclass(frozen=True, slots=True)
class FrameOwnership:
    """The popup rows and the scope label of one frame's canonical owner.

    :data:`UNOWNED` is the Hub's "no name for this owner right now": the frame is
    unowned, its owner is unidentified, or it departed between the snapshot and
    the push. The wire fields it fills mean "no change", never "blank", so the
    Display keeps what it last held. A label needs rows: it is only ever minted
    for a named session, which also has rows to show.
    """

    # None = the Hub has no named live session for the owner (PY-TS-14: absence
    # is the documented contract, and the wire field's own "owner unknown").
    rows: tuple[tuple[str, str], ...] | None = None
    # None = no label to show: either the absence above, or an owner the Hub
    # named no scope for (rows present, label absent).
    scope_label: str | None = None

    def __post_init__(self) -> None:
        if self.rows is None and self.scope_label is not None:
            msg = f"a scope label needs rows: got label {self.scope_label!r} alone"
            raise ValueError(msg)


# The shared "no owner known" value, usable as a parameter default.
UNOWNED = FrameOwnership()
