"""InspectScope — which proxied display facts an ``inspect_scene`` call wants.

The Hub answers ``inspect_scene`` from its authoritative store on its own, but
two extras must be fetched from the running display: the element mirror check and
the painted geometry. Each is a bounded round-trip a caller pays for only when it
asks, so the request carries a flag for each. Bundling the two flags into one
value keeps the operation's signature to ``(scene_id, scope)`` instead of a
widening list of booleans (PY-OO-3), and gives a surface one object to bind.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["HUB_ONLY", "InspectScope"]


class InspectScope(BaseModel):
    """The proxied display facts an inspection wants beyond the Hub's own tree.

    ``want_mirror`` asks the display whether every element is mirrored;
    ``want_geometry`` asks for each painted element's screen rect and the frame
    rect. Both default off, so a bare inspection stays a single Hub-local read.
    """

    model_config = ConfigDict(frozen=True)

    want_mirror: bool = False
    want_geometry: bool = False


# The canonical "neither fact" scope: a bare Hub-local inspection. Frozen, so it
# is a safe shared default (avoids a call-in-argument-default, ruff B008).
HUB_ONLY = InspectScope()
