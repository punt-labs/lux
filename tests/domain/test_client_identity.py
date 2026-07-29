"""ClientIdentity and ClientSession — the declared owner and its session record.

ClientIdentity validates what a client declares (a real kind, a name, an absolute
repo when present) and round-trips through its wire dict; ClientSession pairs a
connect time with the identity and never resets the time when it is declared.
"""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.client_identity import ClientIdentity, ClientSession


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


def test_session_starts_unidentified() -> None:
    session = ClientSession(time.monotonic())
    assert session.identity is None


def test_with_identity_keeps_the_connect_time() -> None:
    stamped = time.monotonic()
    session = ClientSession(stamped)
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")

    declared = session.with_identity(identity)

    assert declared.identity == identity
    assert declared.connected_at == stamped


def test_age_never_goes_negative_under_a_backward_clock_step() -> None:
    session = ClientSession(100.0)
    # A monotonic reading behind the stamp (a stepped clock) still reads zero.
    assert session.age(99.0) == 0.0
    assert session.age(103.5) == pytest.approx(3.5)
