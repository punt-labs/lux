"""SceneReplica's own aggregation of its composed collaborators.

Internal to the ``replica`` package (leading underscore -- not part of the
public surface): PL-CU-1's prescribed remedy (DES-095) for a class that
composes several extracted primitives -- ``scene_replica.py`` imports this
one module instead of importing each composed collaborator directly.
Adding a new composed primitive only ever grows this module's efferent
coupling, never ``scene_replica.py``'s.
"""

from __future__ import annotations

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.manifest_purge import ManifestPurge
from punt_lux.display.replica.stale_ids import OnSceneReplacedFn, StaleIds
from punt_lux.display.replica.widget_state import WidgetState, WireScalar
from punt_lux.display.replica.widget_state_store import WidgetStateStore

__all__ = [
    "Frame",
    "FrameBook",
    "ManifestPurge",
    "OnSceneReplacedFn",
    "StaleIds",
    "WidgetState",
    "WidgetStateStore",
    "WireScalar",
]
