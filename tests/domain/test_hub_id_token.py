"""HubIdToken -- resolving a ConnectMessage.hub_id wire string into a HubId."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub_id import HubId
from punt_lux.domain.hub_id_token import HubIdToken


def test_resolve_round_trips_a_real_hub_ids_wire_token() -> None:
    hub_id = HubId("pembroke", 123)
    assert HubIdToken(hub_id.wire_token).resolve() == hub_id


def test_resolve_round_trips_current() -> None:
    hub_id = HubId.current()
    assert HubIdToken(hub_id.wire_token).resolve() == hub_id


def test_resolve_round_trips_stub() -> None:
    hub_id = HubId.stub()
    assert HubIdToken(hub_id.wire_token).resolve() == hub_id


def test_resolve_rejects_a_token_with_no_separator() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("pembroke123").resolve()


def test_resolve_rejects_a_blank_hostname() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("\x1f123").resolve()


def test_resolve_rejects_a_non_numeric_pid() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("pembroke\x1fabc").resolve()


def test_resolve_rejects_an_empty_string() -> None:
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("").resolve()


def test_resolve_normalizes_a_mixed_case_hostname() -> None:
    # A cross-host peer declaring an upper-case hostname must resolve to the
    # identical HubId a lower-case declaration would -- the wire is not a
    # second, independent place hostname canonicalization could be skipped.
    assert HubIdToken("HUB1.EXAMPLE.COM\x1f123").resolve() == HubId(
        "hub1.example.com", 123
    )


def test_resolve_rejects_a_hostname_embedding_a_second_separator() -> None:
    """A bare ``rpartition`` would accept ``"a\\x1f1"`` as the hostname here --
    a control character must never reach a registry key or a log line."""
    with pytest.raises(ValueError, match="not a HubId wire token"):
        HubIdToken("a\x1f1\x1f2").resolve()
