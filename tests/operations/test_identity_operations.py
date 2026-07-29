"""IdentityOperations — the identify first-call and the introspection it feeds.

Identifying records a validated ClientIdentity against the caller's connection;
a malformed declaration is an ``invalid_request`` naming the field and records
nothing. Sharing one ``HubDisplay`` with a read, an identified session's
``list_clients`` entry carries the record while an unidentified one shows the
connection-only shape. The ``identification_required`` challenge is the shape
PR-2 wires onto the operations that demand identity.
"""

from __future__ import annotations

from collections.abc import Mapping

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.display_reply import DisplayReply
from punt_lux.operations.identity import IdentityOperations
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.identity import Identified
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scope import Scope


class _ForbiddenPort:
    """A DisplayPort that fails the test if a proxied call is made."""

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        msg = f"read reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> DisplayReply:
        msg = f"read reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


def _scope(connection: str) -> Scope:
    return Scope(ConnectionId(connection))


def test_identify_records_the_identity_and_echoes_it() -> None:
    store = HubDisplay()
    ops = IdentityOperations(store)

    result = ops.identify(
        {"kind": "mcp-session", "name": "claude", "repo": "/w/lux", "agent": "claude"},
        scope=_scope("c1"),
    )

    assert isinstance(result, Identified)
    assert result.identity.name == "claude"
    assert result.identity.repo == "/w/lux"
    session = store.client_sessions()[ConnectionId("c1")]
    assert session.identity == result.identity


def test_identify_a_headless_cli_without_a_repo() -> None:
    store = HubDisplay()
    result = IdentityOperations(store).identify(
        {"kind": "cli", "name": "lux-cli"}, scope=_scope("c1")
    )
    assert isinstance(result, Identified)
    assert result.identity.repo is None


def test_bad_kind_is_invalid_request_and_records_nothing() -> None:
    store = HubDisplay()
    result = IdentityOperations(store).identify(
        {"kind": "daemon", "name": "x"}, scope=_scope("c1")
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "kind" in result.reason
    # A rejected declaration binds nothing — the connection stays unregistered.
    assert store.client_sessions() == {}


def test_missing_name_is_invalid_request() -> None:
    store = HubDisplay()
    result = IdentityOperations(store).identify({"kind": "cli"}, scope=_scope("c1"))
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "name" in result.reason


def test_relative_repo_is_invalid_request() -> None:
    store = HubDisplay()
    result = IdentityOperations(store).identify(
        {"kind": "cli", "name": "lux", "repo": "relative/path"}, scope=_scope("c1")
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "repo" in result.reason


def test_list_clients_shows_the_record_only_for_identified_sessions() -> None:
    store = HubDisplay()
    IdentityOperations(store).identify(
        {"kind": "cli", "name": "lux", "repo": "/w/lux"}, scope=_scope("identified")
    )
    store.register_client(ConnectionId("anonymous"))
    reader = QueryOperations(store, Hub(), _ForbiddenPort())

    by_id = {c.connection_id: c for c in reader.list_clients().clients}

    assert by_id["identified"].identity is not None
    assert by_id["identified"].identity.repo == "/w/lux"
    # An unidentified session is a real connection with no declared identity.
    assert by_id["anonymous"].identity is None


def test_identification_required_challenge_constructs_with_its_code() -> None:
    err = OpError.identification_required("identify before installing UI")
    assert err.kind == "error"
    assert err.code == "identification_required"
    assert err.reason == "identify before installing UI"
