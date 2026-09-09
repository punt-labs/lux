"""FrameAccessorDeps — the collaborators one ``FrameAccessor`` composes.

Bundled into one value object so ``FrameAccessor.__new__`` takes one
parameter instead of one per collaborator (PY-OO-3): the three are always
constructed together, by :meth:`LuxClient.frame`, never independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.commands._ports import FrameOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Scope

__all__ = ["FrameAccessorDeps"]


@final
@dataclass(frozen=True, slots=True)
class FrameAccessorDeps:
    """The ops surface, identity, and scope one ``FrameAccessor`` composes."""

    ops: FrameOps
    identity: ClientIdentity
    scope: Scope
