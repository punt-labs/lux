"""HubId -- value tests for a Hub connection's own declared identity."""

from __future__ import annotations

import os
import socket

from punt_lux.domain.hub.hub_id import HubId


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
