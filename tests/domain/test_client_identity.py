"""ClientIdentity — what a client declares itself to be.

ClientIdentity validates what a client declares (a real kind, a name, an absolute
repo when present) and round-trips through its wire dict. The session record that
holds an identity across its lease is :class:`ClientSession`, tested separately.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.client_identity import ClientIdentity


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
