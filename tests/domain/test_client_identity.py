"""ClientIdentity and ClientSession — the declared owner and its session record.

ClientIdentity validates what a client declares (a real kind, a name, an absolute
repo when present) and round-trips through its wire dict. ClientSession pairs that
identity with a connect time and a renewal lease: it starts unidentified with a
grace lease, gains an identity (and that kind's lease length) on declaration
without resetting its connect time, and is renewed by any contact.
"""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.client_identity import ClientIdentity, ClientSession
from punt_lux.domain.hub.session_lease import SessionLease


def test_full_identity_round_trips_through_its_wire_dict() -> None:
    identity = ClientIdentity(
        kind="mcp-session", name="claude", repo="/w/lux", agent="claude"
    )
    assert ClientIdentity.model_validate(identity.model_dump()) == identity


def test_headless_identity_has_no_repo_or_agent() -> None:
    identity = ClientIdentity(kind="cli", name="lux-cli")
    assert identity.repo is None
    assert identity.agent is None
    assert not identity.has_repo


def test_repo_present_reports_has_repo() -> None:
    assert ClientIdentity(kind="cli", name="lux", repo="/w/lux").has_repo


def test_bad_kind_is_rejected_by_name() -> None:
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="daemon", name="x")  # type: ignore[arg-type]
    assert "kind" in str(exc.value)


def test_empty_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientIdentity(kind="cli", name="")


def test_whitespace_only_name_is_rejected() -> None:
    # A blank-after-strip label is not a real attribution — reject it, don't store it.
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="cli", name="   ")
    assert "name" in str(exc.value)


def test_relative_repo_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="cli", name="lux", repo="relative/path")
    assert "repo" in str(exc.value)


def test_blank_repo_is_rejected_rather_than_read_as_headless() -> None:
    with pytest.raises(ValidationError):
        ClientIdentity(kind="cli", name="lux", repo="")


def test_blank_agent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux", agent="")


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientIdentity(kind="cli", name="lux", role="admin")  # type: ignore[call-arg]


def test_session_starts_unidentified_with_a_grace_lease() -> None:
    session = ClientSession(0.0)
    assert session.identity is None
    assert session.is_live(0.0)
    assert not session.is_live(1801.0)  # the unidentified grace has lapsed


def test_with_identity_keeps_the_connect_time_and_sets_the_kind_lease() -> None:
    session = ClientSession(0.0)
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")

    declared = session.with_identity(identity)

    assert declared.identity == identity
    assert declared.connected_at == 0.0
    # A cli session's lease is short: live now, lapsed well before the grace would.
    assert declared.is_live(89.0)
    assert not declared.is_live(91.0)


def test_renewed_keeps_identity_and_connect_time_but_extends_the_lease() -> None:
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    session = ClientSession(0.0).with_identity(identity)
    assert not session.is_live(100.0)  # the original cli lease lapsed by 100s

    renewed = session.renewed(80.0)
    assert renewed.identity == identity
    assert renewed.connected_at == 0.0
    assert renewed.is_live(100.0)  # renewed at 80s, still inside the 90s window


def test_declared_repo_is_the_identity_repo_or_none() -> None:
    assert ClientSession(0.0).declared_repo is None  # unidentified
    declared = ClientSession(0.0).with_identity(
        ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    )
    assert declared.declared_repo == "/w/lux"


def test_age_never_goes_negative_under_a_backward_clock_step() -> None:
    session = ClientSession(100.0)
    # A monotonic reading behind the stamp (a stepped clock) still reads zero.
    assert session.age(99.0) == 0.0
    assert session.age(103.5) == pytest.approx(3.5)


def test_a_supplied_lease_is_held_verbatim() -> None:
    lease = SessionLease(renewed_at=5.0, ttl_seconds=10.0)
    session = ClientSession(0.0, lease=lease)
    assert session.is_live(15.0)
    assert not session.is_live(15.1)


def test_uses_a_real_monotonic_stamp_by_default() -> None:
    # Sanity: a freshly-stamped session is live at the current monotonic reading.
    session = ClientSession(time.monotonic())
    assert session.is_live(time.monotonic())
