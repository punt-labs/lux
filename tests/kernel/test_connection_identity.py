"""ConnectionSeed — one identity, one connection id, whatever shape it arrives in.

The id is what makes a client's REST calls and its WebSocket the same Hub
session, so two callers holding the same identity must derive the same id. The
two shapes a declaration really comes in are a header read (absent keys omitted)
and a model dump (absent keys explicitly ``None``), and these pin that they agree.
"""

from __future__ import annotations

from punt_lux.kernel.connection_identity import ConnectionSeed
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.model.identity_headers import ClientHeaders


def _from_headers(identity: ClientIdentity) -> str:
    """Derive the id the way both production legs do: through the header contract."""
    declaration = ClientHeaders.declaration_from(ClientHeaders.to_wire(identity))
    assert declaration is not None  # a named identity always renders a declaration
    return str(ConnectionSeed(declaration).connection_id)


def test_a_model_dump_and_a_header_read_agree() -> None:
    """An app holding a ClientIdentity derives the id its own WebSocket will get."""
    identity = ClientIdentity(kind="app", name="voxd", repo="/w/vox")
    assert str(ConnectionSeed(identity.model_dump()).connection_id) == _from_headers(
        identity
    )


def test_they_agree_for_a_headless_identity_too() -> None:
    """The case that used to diverge: every optional field absent."""
    identity = ClientIdentity(kind="cli", name="lux-cli")
    assert str(ConnectionSeed(identity.model_dump()).connection_id) == _from_headers(
        identity
    )


def test_a_declared_lease_does_not_change_the_connection() -> None:
    """The lease is how long a session may idle, not who it is."""
    plain = ClientIdentity(kind="mcp-session", name="lux#1", repo="/w/lux")
    leased = ClientIdentity(
        kind="mcp-session", name="lux#1", repo="/w/lux", lease_ttl=60.0
    )
    assert (
        ConnectionSeed(plain.model_dump()).connection_id
        == ConnectionSeed(leased.model_dump()).connection_id
    )


def test_distinct_identities_never_collide() -> None:
    names = ("lux#1", "lux#2")
    ids = {
        ConnectionSeed(
            ClientIdentity(kind="mcp-session", name=name, repo="/w/lux").model_dump()
        ).connection_id
        for name in names
    }
    assert len(ids) == len(names)


def test_the_repository_is_part_of_the_identity() -> None:
    """Two sessions of one name in two repositories are two connections."""
    first = ClientIdentity(kind="mcp-session", name="lux#1", repo="/w/lux")
    second = ClientIdentity(kind="mcp-session", name="lux#1", repo="/w/vox")
    assert (
        ConnectionSeed(first.model_dump()).connection_id
        != ConnectionSeed(second.model_dump()).connection_id
    )


def test_the_same_repository_on_two_hosts_is_two_connections() -> None:
    base = {"kind": "app", "name": "luxd-pty", "repo": "/w/lux"}
    assert (
        ConnectionSeed({**base, "host": "okinos"}).connection_id
        != ConnectionSeed({**base, "host": "pembroke"}).connection_id
    )
