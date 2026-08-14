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


def test_a_client_is_named_for_the_repository_it_works_in() -> None:
    """The menu calls a client after where it works, not what it declared."""
    identity = ClientIdentity(kind="applet", name="lux · lux · #4b97", repo="/w/lux")
    assert identity.menu_label == "lux"


def test_a_client_with_no_repository_is_named_for_itself() -> None:
    assert ClientIdentity(kind="app", name="voxd").menu_label == "voxd"


def test_a_trailing_slash_still_reads_as_the_directory() -> None:
    identity = ClientIdentity(kind="cli", name="lux-cli", repo="/w/lux/")
    assert identity.menu_label == "lux"


@pytest.mark.parametrize("repo", ["/", "//", "/.", "/./", "/ "])
def test_a_repository_that_names_no_directory_falls_back_to_the_name(repo: str) -> None:
    """A root path is absolute, so it is accepted — and it has no basename.

    The label it once produced was blank, which the Menu model rejects, so one
    client running from ``/`` threw where the Clients menu was composed and took
    every other client's entry down with it.
    """
    assert ClientIdentity(kind="cli", name="lux-cli", repo=repo).menu_label == "lux-cli"


@pytest.mark.parametrize(
    "repo", [None, "/w/lux", "/w/lux/", "/", "//", "/.", "/./", "/ ", "/w/ lux "]
)
def test_no_identity_the_registry_can_hold_has_a_blank_label(repo: str | None) -> None:
    """The label is total: every accepted identity has one a menu can carry."""
    label = ClientIdentity(kind="cli", name="lux-cli", repo=repo).menu_label
    assert label == label.strip() != ""


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


def test_a_windows_style_path_is_relative_here_and_is_rejected() -> None:
    """POSIX is the flavour luxd resolves paths in, so ``C:\\w`` is not absolute."""
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="cli", name="lux", repo="C:\\w\\lux")
    assert "repo" in str(exc.value)


def test_blank_repo_is_rejected_rather_than_read_as_headless() -> None:
    with pytest.raises(ValidationError):
        ClientIdentity(kind="cli", name="lux", repo="")


def test_blank_agent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux", agent="")


def test_a_nul_in_name_is_rejected() -> None:
    """name is the field most exposed to caller-supplied content, e.g. via headers."""
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="app", name="foo\x00bar")
    assert "NUL" in str(exc.value)


def test_a_nul_in_repo_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="cli", name="lux", repo="/tmp\x00/x")
    assert "NUL" in str(exc.value)


def test_a_nul_in_agent_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="mcp-session", name="claude", agent="me\x00you")
    assert "NUL" in str(exc.value)


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientIdentity(kind="cli", name="lux", role="admin")  # type: ignore[call-arg]


def test_absent_lease_ttl_is_none_the_kind_default() -> None:
    # Absence is the documented "use my kind's default" state, not a give-up.
    assert ClientIdentity(kind="app", name="voxd").lease_ttl is None


def test_a_declared_lease_ttl_in_bounds_is_kept() -> None:
    identity = ClientIdentity(kind="app", name="voxd", lease_ttl=30.0)
    assert identity.lease_ttl == 30.0
    assert ClientIdentity.model_validate(identity.model_dump()) == identity


def test_a_lease_ttl_below_the_floor_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="app", name="voxd", lease_ttl=1.0)
    assert "lease_ttl" in str(exc.value)


def test_a_lease_ttl_above_the_cap_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        ClientIdentity(kind="cli", name="cron", lease_ttl=7200.0)
    assert "lease_ttl" in str(exc.value)


def test_the_cron_twenty_minute_cadence_is_within_bounds() -> None:
    # The operator's example: a cron client declares a 20-minute lease.
    assert ClientIdentity(kind="cli", name="cron", lease_ttl=1200.0).lease_ttl == 1200.0
