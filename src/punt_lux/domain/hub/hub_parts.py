"""HubParts — the wired collaborators of one Hub store, each a narrow port.

``HubDisplay`` coordinates writes across the store; everything else a caller asks of
it is answered by exactly one collaborator, so callers hold that collaborator rather
than the facade: ``lifecycle`` for client arrival, contact and departure; ``clients``
for the session registry; ``reads`` for element, owner and session reads; ``reader``
for the replicator's snapshots and live scene ids; ``frames`` for presentations and
TTL expiry; ``quarantines`` for quarantine records; ``dismissal`` and ``seam`` for the
write path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
    from punt_lux.domain.hub.dismissal_walk import DismissalWalk
    from punt_lux.domain.hub.frame_lifecycle import FrameLifecycle
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.hub_reads import HubReads
    from punt_lux.domain.hub.scene_quarantine import SceneQuarantine
    from punt_lux.domain.hub.scene_snapshot import SceneReader
    from punt_lux.domain.hub.write_seam import WriteSeam

__all__ = ["HubParts"]


@final
@dataclass(frozen=True, slots=True)
class HubParts:
    """The collaborators a ``HubDisplay`` composes, handed out as one record."""

    lifecycle: ClientLifecycle
    clients: HubClientRegistry
    reads: HubReads
    reader: SceneReader
    frames: FrameLifecycle
    quarantines: SceneQuarantine
    dismissal: DismissalWalk
    seam: WriteSeam
