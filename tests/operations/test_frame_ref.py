"""FrameRef -- a caller's local frame name, paired with the scope that names it."""

from __future__ import annotations

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.frame_ref import FrameRef
from punt_lux.operations.scope import Scope


def test_of_composes_from_a_scope() -> None:
    scope = Scope(ConnectionId("c1"))
    ref = FrameRef.of("beads-lux", scope=scope)
    assert ref == FrameRef(ConnectionId("c1"), "beads-lux")


def test_for_identity_composes_from_a_declared_identity() -> None:
    identity = ClientIdentity(kind="cli", name="lux-cli", repo="/w/lux")
    ref = FrameRef.for_identity("beads-lux", identity)
    assert ref == FrameRef(identity.connection_id, "beads-lux")


def test_for_identity_matches_of_for_the_same_identity_scope() -> None:
    """The two constructors agree -- one identity resolves to one connection."""
    identity = ClientIdentity(kind="cli", name="lux-cli", repo="/w/lux")
    scope = Scope(identity.connection_id)
    assert FrameRef.for_identity("beads-lux", identity) == FrameRef.of(
        "beads-lux", scope=scope
    )


def test_scoped_composes_the_connection_scoped_store_key() -> None:
    ref = FrameRef(ConnectionId("c1"), "beads-lux")
    assert ref.scoped() == ConnectionScopedId.compose(ConnectionId("c1"), "beads-lux")
