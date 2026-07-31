"""connection_for — one identity, one connection id, whatever shape it arrives in.

The id is what makes a client's REST calls and its WebSocket the same Hub
session, so two callers holding the same identity must derive the same id. The
two shapes a declaration really comes in are a header read (absent keys omitted)
and a model dump (absent keys explicitly ``None``), and these pin that they agree.
"""

from __future__ import annotations

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.identity_headers import ClientHeaders


def _from_headers(identity: ClientIdentity) -> str:
    """Derive the id the way both production legs do: through the header contract."""
    declaration = ClientHeaders.declaration_from(ClientHeaders.to_wire(identity))
    assert declaration is not None  # a named identity always renders a declaration
    return str(connection_for(declaration))


def test_a_model_dump_and_a_header_read_agree() -> None:
    """An app holding a ClientIdentity derives the id its own WebSocket will get."""
    identity = ClientIdentity(kind="app", name="voxd", repo="/w/vox")
    assert str(connection_for(identity.model_dump())) == _from_headers(identity)


def test_they_agree_for_a_headless_identity_too() -> None:
    """The case that used to diverge: every optional field absent."""
    identity = ClientIdentity(kind="cli", name="lux-cli")
    assert str(connection_for(identity.model_dump())) == _from_headers(identity)


def test_a_declared_lease_does_not_change_the_connection() -> None:
    """The lease is how long a session may idle, not who it is."""
    plain = ClientIdentity(kind="mcp-session", name="lux#1", repo="/w/lux")
    leased = ClientIdentity(
        kind="mcp-session", name="lux#1", repo="/w/lux", lease_ttl=60.0
    )
    assert connection_for(plain.model_dump()) == connection_for(leased.model_dump())


def test_distinct_identities_never_collide() -> None:
    names = ("lux#1", "lux#2")
    ids = {
        connection_for(
            ClientIdentity(kind="mcp-session", name=name, repo="/w/lux").model_dump()
        )
        for name in names
    }
    assert len(ids) == len(names)


def test_the_repository_is_part_of_the_identity() -> None:
    """Two sessions of one name in two repositories are two connections."""
    first = ClientIdentity(kind="mcp-session", name="lux#1", repo="/w/lux")
    second = ClientIdentity(kind="mcp-session", name="lux#1", repo="/w/vox")
    assert connection_for(first.model_dump()) != connection_for(second.model_dump())
