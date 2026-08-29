"""``Ctx`` -- the collaborators every command shares.

Split out of ``_result`` (DES-065 OO paydown): ``Ctx`` is the per-call bundle
a command reads its collaborators from, distinct from the ``OpsPort``
protocol those collaborators satisfy and from ``CommandResult``, the shape a
command hands back. Three reasons to change, three modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from punt_lux.commands._ops_port import OpsPort

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["Ctx"]


@dataclass(frozen=True, slots=True)
class Ctx:
    """Collaborators shared by every command.

    Attributes:
        ops: The operations surface -- ``Operations`` in-process, or a client
            that structurally satisfies :class:`OpsPort` across the process
            boundary.
        identity: The caller's declared identity (DES-086). Later commands key
            store lookups by ``identity.name`` / ``identity.repo`` /
            ``identity.agent``; PingCommand does not read it, but Ctx carries
            it now so the shape is fixed before it multiplies.
    """

    ops: OpsPort
    identity: ClientIdentity
