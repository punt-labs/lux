"""InspectScope — which proxied display facts an ``inspect_scene`` call wants.

The Hub answers ``inspect_scene`` from its authoritative store on its own, but
two extras must be fetched from the running display: the painted geometry, and
where each frame is being shown. Each is a bounded round-trip a caller pays for
only when it asks, so the request carries a flag for each. Kept as its own
value type (rather than bare bool parameters) so an operation's signature stays
``(..., scope)`` and a surface has one object to bind — the shape that let the
retired mirror flag live here without widening the parameter list, and that is
how ``want_visibility`` joined it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["HUB_ONLY", "InspectScope"]


class InspectScope(BaseModel):
    """The proxied display facts an inspection wants beyond the Hub's own tree.

    ``want_geometry`` asks for each painted element's screen rect and the frame
    rect. ``want_visibility`` asks where the display is showing each frame ---
    on screen, docked, or put away by the user, which the Hub does not hold
    because it is never replicated back (DES-088). Both default off, so a bare
    read stays a single Hub-local one and never reaches around to the display.
    """

    model_config = ConfigDict(frozen=True)

    want_geometry: bool = False
    want_visibility: bool = False


# The canonical "neither fact" scope: a bare Hub-local inspection. Frozen, so it
# is a safe shared default (avoids a call-in-argument-default, ruff B008).
HUB_ONLY = InspectScope()
