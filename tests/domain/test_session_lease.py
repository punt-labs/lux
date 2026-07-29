"""SessionLease — the renewal-and-length that decides whether a session is live.

The lease is pure time arithmetic keyed off a kind's declared length: a cli lease
is short, an mcp-session lease generous, an app lease unbounded. These pin the
boundary and the per-kind lengths a test clock drives the registry expiry with.
"""

from __future__ import annotations

import math

from punt_lux.domain.hub.session_lease import SessionLease


def test_live_until_the_ttl_elapses() -> None:
    lease = SessionLease(renewed_at=100.0, ttl_seconds=90.0)
    assert lease.is_live(100.0)
    assert lease.is_live(190.0)  # exactly at the boundary is still live
    assert not lease.is_live(190.1)


def test_renewed_pushes_the_window_forward_keeping_the_length() -> None:
    lease = SessionLease(renewed_at=100.0, ttl_seconds=90.0)
    later = lease.renewed(300.0)
    assert later.ttl_seconds == 90.0
    assert not lease.is_live(300.0)  # the original had lapsed
    assert later.is_live(300.0)  # the renewal is live again


def test_cli_lease_is_short_and_mcp_lease_is_generous() -> None:
    cli = SessionLease.for_kind("cli", 0.0)
    mcp = SessionLease.for_kind("mcp-session", 0.0)
    assert cli.ttl_seconds == 90.0
    assert mcp.ttl_seconds == 1800.0
    assert cli.ttl_seconds < mcp.ttl_seconds


def test_app_lease_never_lapses() -> None:
    app = SessionLease.for_kind("app", 0.0)
    assert app.ttl_seconds == math.inf
    assert app.is_live(1e12)  # an app built-in stays live for the whole process


def test_unidentified_grace_matches_the_mcp_length() -> None:
    # A connected-but-unidentified session is an MCP session mid-handshake, so its
    # grace is the generous length, not the short cli one.
    assert SessionLease.unidentified(0.0).ttl_seconds == 1800.0


def test_a_declared_ttl_overrides_the_kind_default() -> None:
    # A daemon declares a short lease even though its "app" kind would be permanent.
    lease = SessionLease.for_declared("app", 30.0, 0.0)
    assert lease.ttl_seconds == 30.0
    assert not lease.is_live(31.0)


def test_an_absent_declared_ttl_falls_to_the_kind_default() -> None:
    # No declaration → the kind default, so luxd's built-in app stays permanent.
    assert SessionLease.for_declared("app", None, 0.0).ttl_seconds == math.inf
    assert SessionLease.for_declared("cli", None, 0.0).ttl_seconds == 90.0
