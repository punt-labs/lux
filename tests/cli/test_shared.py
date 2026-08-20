"""Unit tests for :func:`punt_lux.cli._shared.identity_from_flags`."""

from __future__ import annotations

import pytest
import typer

from punt_lux.cli._shared import identity_from_flags


def test_valid_flags_resolve_a_client_identity() -> None:
    identity = identity_from_flags(
        as_=None, kind="cli", name="test-driver", repo=None, agent=None
    )
    assert identity.kind == "cli"
    assert identity.name == "test-driver"


def test_invalid_kind_reports_a_clean_usage_error_not_a_traceback() -> None:
    """Regression: an invalid --kind used to raise pydantic ValidationError
    unhandled (Bugbot MEDIUM)."""
    with pytest.raises(typer.BadParameter) as exc_info:
        identity_from_flags(
            as_=None, kind="bogus", name="test-driver", repo=None, agent=None
        )
    assert "--kind" in str(exc_info.value)


def test_relative_repo_reports_a_clean_usage_error_not_a_traceback() -> None:
    with pytest.raises(typer.BadParameter) as exc_info:
        identity_from_flags(
            as_=None,
            kind="cli",
            name="test-driver",
            repo="relative/path",
            agent=None,
        )
    assert "--repo" in str(exc_info.value)
    assert "absolute path" in str(exc_info.value)


def test_empty_agent_clears_rather_than_validates() -> None:
    """An empty --agent means 'no agent', not a validation failure -- the
    min_length=1 constraint only applies to a genuinely present value."""
    identity = identity_from_flags(
        as_=None, kind="cli", name="test-driver", repo=None, agent=""
    )
    assert identity.agent is None
