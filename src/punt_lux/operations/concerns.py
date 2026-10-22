"""OperationsConcerns — the concern objects one ``Operations`` facade composes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.operations.callbacks import CallbackOperations
    from punt_lux.operations.config import DisplayModeOperations
    from punt_lux.operations.display_control import DisplayControlOperations
    from punt_lux.operations.display_link import DisplayLinkOperations
    from punt_lux.operations.frame_removal import FrameRemover
    from punt_lux.operations.identity import IdentityOperations
    from punt_lux.operations.menu_arming import MenuArming
    from punt_lux.operations.menus import MenuOperations
    from punt_lux.operations.pubsub import PubSubOperations
    from punt_lux.operations.queries import QueryOperations
    from punt_lux.operations.scenes import SceneOperations

__all__ = ["OperationsConcerns"]


@final
@dataclass(frozen=True, slots=True)
class OperationsConcerns:
    """The eleven concerns, bundled so ``Operations.__new__`` takes one (PY-OO-3)."""

    scenes: SceneOperations
    pubsub: PubSubOperations
    config: DisplayModeOperations
    display: DisplayControlOperations
    queries: QueryOperations
    menus: MenuOperations
    arming: MenuArming
    identity: IdentityOperations
    callbacks: CallbackOperations
    frame_remover: FrameRemover
    link: DisplayLinkOperations
