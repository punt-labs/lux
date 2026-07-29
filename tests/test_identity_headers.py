"""ClientHeaders — the one X-Lux-Client-* contract, both directions.

The client renders an identity into headers and the Hub reads them back; the two
must agree. These tests pin the round trip and the absence rules that keep a blank
header from reaching ``identify`` as a malformed field.
"""

from __future__ import annotations

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
