"""ClientHeaders — the one X-Lux-Client-* contract, both directions.

The client renders an identity into headers and the Hub reads them back; the two
must agree. These tests pin the round trip and the absence rules that keep a blank
header from reaching ``identify`` as a malformed field.
"""

from __future__ import annotations

import pytest

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.identity_headers import ClientHeaders


def test_to_wire_carries_kind_name_repo_and_agent() -> None:
    identity = ClientIdentity(
        kind="mcp-session", name="claude", repo="/w/lux", agent="gvr"
    )
    assert ClientHeaders.to_wire(identity) == {
        "X-Lux-Client-Kind": "mcp-session",
        "X-Lux-Client-Name": "claude",
        "X-Lux-Client-Repo": "/w/lux",
        "X-Lux-Client-Agent": "gvr",
    }


def test_to_wire_omits_absent_repo_and_agent() -> None:
    # A headless CLI owns no repo and carries no agent; absent fields are omitted,
    # never sent blank — a blank header equals no header on the read side.
    identity = ClientIdentity(kind="cli", name="lux-cli")
    assert ClientHeaders.to_wire(identity) == {
        "X-Lux-Client-Kind": "cli",
        "X-Lux-Client-Name": "lux-cli",
    }


def test_round_trips_through_a_declaration() -> None:
    identity = ClientIdentity(kind="cli", name="vox", repo="/w/vox")
    declaration = ClientHeaders.declaration_from(ClientHeaders.to_wire(identity))
    assert declaration == {"kind": "cli", "name": "vox", "repo": "/w/vox"}


def test_declaration_is_none_without_a_name() -> None:
    assert ClientHeaders.declaration_from({"X-Lux-Client-Repo": "/w/lux"}) is None


def test_declaration_defaults_kind_to_cli() -> None:
    declaration = ClientHeaders.declaration_from({"X-Lux-Client-Name": "tool"})
    assert declaration == {"kind": "cli", "name": "tool"}


def test_blank_optional_header_is_dropped() -> None:
    # A whitespace-only repo must not reach identify (which rejects a blank repo).
    declaration = ClientHeaders.declaration_from(
        {"X-Lux-Client-Name": "tool", "X-Lux-Client-Repo": "   "}
    )
    assert declaration == {"kind": "cli", "name": "tool"}


def test_blank_kind_falls_back_to_the_cli_default() -> None:
    # A whitespace-only kind equals no kind — stripped and defaulted to cli, not
    # forwarded as an empty string that identify would reject.
    declaration = ClientHeaders.declaration_from(
        {"X-Lux-Client-Name": "tool", "X-Lux-Client-Kind": "   "}
    )
    assert declaration == {"kind": "cli", "name": "tool"}


def test_a_declared_lease_ttl_crosses_both_directions() -> None:
    # The daemon's declared cadence rides the same header set REST and the WS
    # handshake read, so both legs see the same lease.
    identity = ClientIdentity(kind="app", name="voxd", lease_ttl=30.0)
    wire = ClientHeaders.to_wire(identity)
    assert wire["X-Lux-Client-Lease-Ttl"] == "30.0"
    declaration = ClientHeaders.declaration_from(wire)
    assert ClientIdentity.model_validate(declaration) == identity


def test_an_absent_lease_ttl_sends_no_header() -> None:
    # An undeclared TTL is omitted, not sent blank — the read side reads the kind
    # default, and luxd's built-ins stay permanent.
    assert "X-Lux-Client-Lease-Ttl" not in ClientHeaders.to_wire(
        ClientIdentity(kind="app", name="luxd")
    )


def test_a_non_ascii_identity_crosses_as_ascii_and_reads_back_whole() -> None:
    """The wire carries ASCII, so a name or path with an accent survives it.

    Left alone, the transports disagree: the WebSocket client sends UTF-8 bytes
    where the HTTP client sends latin-1, and a server decoding one as the other
    reads a different string. That splits one session's two legs onto two
    connection ids, and the callbacks registered on one become invisible to the
    other — the session's menu entry stops working with no error anywhere.
    """
    identity = ClientIdentity(
        kind="mcp-session", name="lux · quarry · #2a", repo="/Users/josé/quarry"
    )
    wire = ClientHeaders.to_wire(identity)

    assert all(value.isascii() for value in wire.values())
    assert ClientIdentity.model_validate(ClientHeaders.declaration_from(wire)) == (
        identity
    )


def test_both_legs_of_one_identity_resolve_to_one_connection() -> None:
    """The property that matters: same identity, same connection, either transport.

    Each transport hands its own header encoding to the server; both must land on
    the id the other did, or a callback registered over REST is delivered to a
    connection the WebSocket never bound.
    """
    identity = ClientIdentity(
        kind="mcp-session", name="lux · lux · #6d18", repo="/w/lux"
    )
    wire = ClientHeaders.to_wire(identity)

    as_utf8 = {k: v.encode().decode("latin-1") for k, v in wire.items()}
    as_latin1 = {k: v.encode("latin-1").decode("latin-1") for k, v in wire.items()}

    assert connection_for(
        ClientHeaders.declaration_from(as_utf8) or {}
    ) == connection_for(ClientHeaders.declaration_from(as_latin1) or {})


def test_an_ascii_value_crosses_the_wire_unchanged() -> None:
    """Existing callers are byte-identical on the wire; only non-ASCII is escaped."""
    identity = ClientIdentity(kind="app", name="voxd", repo="/w/vox")
    wire = ClientHeaders.to_wire(identity)
    assert wire["X-Lux-Client-Name"] == "voxd"
    assert wire["X-Lux-Client-Repo"] == "/w/vox"


def test_a_percent_in_a_value_round_trips() -> None:
    """Encoding the escape character itself is what keeps the decode faithful."""
    identity = ClientIdentity(kind="cli", name="100%", repo="/w/a%b")
    wire = ClientHeaders.to_wire(identity)
    assert ClientIdentity.model_validate(ClientHeaders.declaration_from(wire)) == (
        identity
    )


@pytest.mark.parametrize(
    "name",
    [
        "ascii-only-90001",
        "z-spec zspec 90001",  # ASCII and spaces
        "z-spec·zspec·90001",  # U+00B7, no spaces
        "z-spec · zspec · 90001",  # spaces and U+00B7 — the real session label
    ],
)
def test_a_client_that_sends_raw_values_resolves_to_one_connection(name: str) -> None:
    """The read must reconcile the transports for a client that does not encode.

    Encoding only governs the clients we ship. A third-party client, or one on a
    released punt-lux, sends its identity raw — and then the WebSocket leg's UTF-8
    bytes and the HTTP leg's latin-1 bytes reach a server that decodes both as
    latin-1, which reads two different names for one identity. Those hash to two
    connection ids, so the callback such a client registers over REST is registered
    on a connection its WebSocket never bound, and the Hub refuses it for holding
    no listen leg. The read recovers the UTF-8 leg, so both legs land on one
    connection whatever the client did.

    The names are the bisect that found this: ASCII passes, ASCII with spaces
    passes, and the U+00B7 the session label uses is where the two legs part.
    """
    over_websocket = {"X-Lux-Client-Kind": "app", "X-Lux-Client-Name": name}
    over_http = dict(over_websocket)
    # What each transport's encoding leaves the latin-1-decoding server holding.
    over_websocket["X-Lux-Client-Name"] = name.encode().decode("latin-1")
    over_http["X-Lux-Client-Name"] = name.encode("latin-1").decode("latin-1")

    from_websocket = ClientHeaders.declaration_from(over_websocket) or {}
    from_http = ClientHeaders.declaration_from(over_http) or {}

    assert from_websocket["name"] == name
    assert connection_for(from_websocket) == connection_for(from_http)
