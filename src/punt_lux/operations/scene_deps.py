"""SceneOperationsDeps — the collaborators one ``SceneOperations`` composes.

Bundled into one value object so ``SceneOperations.__new__`` takes one
parameter instead of one per collaborator (PY-OO-3): the four are always
constructed together, by :meth:`Operations.for_store` or a test's own
factory, never independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.ports import DirtyMarker, ElementFactoryFor

__all__ = ["SceneOperationsDeps"]


@final
@dataclass(frozen=True, slots=True)
class SceneOperationsDeps:
    """The four collaborators one ``SceneOperations`` instance is built from."""

    display: HubDisplay
    replicator: DirtyMarker
    element_factory: ElementFactoryFor
    hub: Hub
