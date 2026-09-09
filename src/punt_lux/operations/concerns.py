"""OperationsConcerns — the concern objects a single ``Operations`` facade composes.

Bundled into one value object so ``Operations.__new__`` takes one parameter
instead of one per concern (PY-OO-3): the concern set only ever grows together,
constructed once by :meth:`Operations.for_store`, so there is no caller that
benefits from naming each concern as its own keyword argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.operations.callbacks import CallbackOperations
    from punt_lux.operations.config import DisplayModeOperations
    from punt_lux.operations.display_control import DisplayControlOperations
    from punt_lux.operations.frame_closing import FrameCloser
    from punt_lux.operations.identity import IdentityOperations
    from punt_lux.operations.menus import MenuOperations
    from punt_lux.operations.pubsub import PubSubOperations
    from punt_lux.operations.queries import QueryOperations
    from punt_lux.operations.scenes import SceneOperations

__all__ = ["OperationsConcerns"]


@final
@dataclass(frozen=True, slots=True)
class OperationsConcerns:
    """The nine concern objects one ``Operations`` facade composes."""

    scenes: SceneOperations
    pubsub: PubSubOperations
    config: DisplayModeOperations
    display: DisplayControlOperations
    queries: QueryOperations
    menus: MenuOperations
    identity: IdentityOperations
    callbacks: CallbackOperations
    frame_closer: FrameCloser
