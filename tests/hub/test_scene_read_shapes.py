"""Hub evidence becomes wire values without moving server types into wire."""

from __future__ import annotations

import pytest

from punt_lux.hub.owner import Owner
from punt_lux.hub.quarantine_record import QuarantineRecord
from punt_lux.hub.scene_read_shapes import SceneReadShapes
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.model.client_identity import ClientIdentity


@pytest.mark.parametrize("identity", [None, ClientIdentity(kind="cli", name="lux")])
def test_owner_shape_retains_declared_identity(identity: ClientIdentity | None) -> None:
    result = SceneReadShapes.owner(Owner(ConnectionId("owner"), identity))
    assert result.connection_id == "owner"
    assert result.identity == identity


@pytest.mark.parametrize("error", [None, "renderer failed"])
def test_quarantine_shape_retains_evidence_and_optional_error(
    error: str | None,
) -> None:
    record = QuarantineRecord(death_count=2, last_death_at=3.5, render_error=error)
    assert SceneReadShapes.quarantine(record).model_dump() == {
        "status": "quarantined",
        "death_count": 2,
        "last_death_at": 3.5,
        "render_error": error,
    }


def test_empty_scene_has_no_owner_shapes() -> None:
    assert SceneReadShapes.owners(()) == []
