"""HubId -- value tests for a Hub connection's own declared identity."""

from __future__ import annotations

import os
import socket

import pytest

from punt_lux.domain.hub_id import HubId


def test_current_reports_this_process_fqdn_and_pid() -> None:
    hub_id = HubId.current()
    assert hub_id.hostname == socket.getfqdn()
    assert hub_id.pid == os.getpid()


def test_wire_token_joins_hostname_and_pid_with_the_unit_separator() -> None:
    hub_id = HubId("pembroke", 123)
    assert hub_id.wire_token == "pembroke\x1f123"


def test_two_hub_ids_with_the_same_fields_are_equal() -> None:
    assert HubId("pembroke", 123) == HubId("pembroke", 123)


def test_two_hub_ids_with_different_pids_are_not_equal() -> None:
    assert HubId("pembroke", 123) != HubId("pembroke", 456)


def test_two_hub_ids_with_different_hostnames_are_not_equal() -> None:
    assert HubId("pembroke", 123) != HubId("otherhost", 123)


def test_stub_is_a_fixed_synthetic_identity() -> None:
    assert HubId.stub() == HubId.stub()


def test_stub_hostname_can_never_resolve() -> None:
    """RFC 2606 reserves ``.invalid`` so the stub can never collide with a
    real HubId.current()."""
    assert HubId.stub().hostname.endswith(".invalid")


def test_stub_never_equals_a_real_current_identity() -> None:
    assert HubId.stub() != HubId.current()


def test_stub_wire_token_is_non_blank() -> None:
    assert HubId.stub().wire_token.strip()


def test_is_frozen() -> None:
    # A HubId is a dict/registry/HubScopedStore key; a post-construction write
    # would corrupt the hash of an already-inserted key.
    hub_id = HubId("pembroke", 123)
    with pytest.raises(AttributeError):
        hub_id.pid = 456  # type: ignore[misc]  # proving frozen=True raises


class TestHostnameCanonicalization:
    """The identity/preemption bypass: a declared-hostname case difference
    must never mint a second, distinct HubId for the same host."""

    def test_hostname_is_lowercased_at_construction(self) -> None:
        assert HubId("HUB1.EXAMPLE.COM", 1).hostname == "hub1.example.com"

    def test_two_hub_ids_differing_only_in_hostname_case_are_equal(self) -> None:
        assert HubId("HUB1.EXAMPLE.COM", 1) == HubId("hub1.example.com", 1)

    def test_two_hub_ids_differing_only_in_hostname_case_hash_equal(self) -> None:
        assert hash(HubId("HUB1.EXAMPLE.COM", 1)) == hash(HubId("hub1.example.com", 1))

    def test_wire_token_is_lowercase_regardless_of_declared_case(self) -> None:
        assert HubId("Pembroke", 123).wire_token == "pembroke\x1f123"

    def test_a_non_ascii_hostname_is_rejected(self) -> None:
        # Unicode-aware folding (str.casefold()) would be needed to compare
        # a non-ASCII hostname case-insensitively, and casefold collides
        # distinct strings ("faß" -> "fass") -- exactly the masquerade this
        # rejection exists to close instead of trading for.
        with pytest.raises(ValueError, match="must be ASCII"):
            HubId("faß.example", 1)
