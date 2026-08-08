"""InspectScope — which proxied display facts an ``inspect_scene`` call wants.

The Hub answers ``inspect_scene`` from its authoritative store on its own, but
one extra must be fetched from the running display: the painted geometry. It is
a bounded round-trip a caller pays for only when it asks, so the request carries
a flag for it. Kept as its own value type (rather than a bare bool parameter) so
the operation's signature stays ``(scene_id, scope)`` and a surface has one
object to bind — the shape that let the retired mirror flag live here without
widening the operation's parameter list, and that still holds for the next
proxied display fact.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["HUB_ONLY", "InspectScope"]


class InspectScope(BaseModel):
    """The proxied display facts an inspection wants beyond the Hub's own tree.

    ``want_geometry`` asks for each painted element's screen rect and the frame
    rect. Defaults off, so a bare inspection stays a single Hub-local read.
    """

    model_config = ConfigDict(frozen=True)

    want_geometry: bool = False


# The canonical "neither fact" scope: a bare Hub-local inspection. Frozen, so it
# is a safe shared default (avoids a call-in-argument-default, ruff B008).
HUB_ONLY = InspectScope()
