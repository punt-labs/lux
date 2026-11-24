"""Convert Hub ownership and quarantine evidence into public wire read shapes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.wire.operations.query_ownership import SceneOwner
from punt_lux.wire.operations.query_quarantine import QuarantineInfo

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.hub.owner import Owner
    from punt_lux.hub.quarantine_record import QuarantineRecord

__all__ = ["SceneReadShapes"]


class SceneReadShapes:
    """Build client-visible values without exposing the store's record classes."""

    @staticmethod
    def owner(owner: Owner) -> SceneOwner:
        """Describe an owner, retaining an absent declared identity as None."""
        return SceneOwner(
            connection_id=str(owner.connection_id), identity=owner.identity
        )

    @classmethod
    def owners(cls, owners: Iterable[Owner]) -> list[SceneOwner]:
        """Describe owners in their store order, including an empty scene."""
        return [cls.owner(owner) for owner in owners]

    @staticmethod
    def quarantine(record: QuarantineRecord) -> QuarantineInfo:
        """Describe attributed deaths and any captured renderer error."""
        return QuarantineInfo(
            death_count=record.death_count,
            last_death_at=record.last_death_at,
            render_error=record.render_error,
        )
