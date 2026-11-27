"""Unit tests for the shared CLI identity flags and command runner."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from punt_lux.cli._shared import OutputFlags, identity_from_flags, run
from punt_lux.client.cli_identity import CliIdentity
from punt_lux.commands import CommandResult
from punt_lux.wire.model.client_identity import ClientIdentity


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


def _command_app(outcome: CommandResult) -> typer.Typer:
    app = typer.Typer()

    async def _command() -> CommandResult:
        return outcome

    @app.command()
    def probe() -> None:
        run(_command(), OutputFlags(json_out=False, verbose=False, quiet=True))

    @app.command()
    def other() -> None:
        """Keep ``probe`` a named subcommand."""

    return app


def test_a_successful_command_logs_its_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _command_app(CommandResult(text="pong"))

    with caplog.at_level("INFO", logger="punt_lux.cli._shared"):
        result = CliRunner().invoke(app, ["probe"], prog_name="lux")

    assert result.exit_code == 0
    assert caplog.messages == ["CLI lux probe succeeded"]


def test_a_failed_command_logs_its_code_not_its_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _command_app(
        CommandResult(
            text="not running",
            json_data={"code": "display_unavailable", "reason": "private detail"},
            error=True,
            exit_code=1,
        )
    )

    with caplog.at_level("INFO", logger="punt_lux.cli._shared"):
        result = CliRunner().invoke(app, ["probe"], prog_name="lux")

    assert result.exit_code == 1
    assert caplog.messages == ["CLI lux probe failed: display_unavailable"]


def test_a_failure_without_a_code_logs_its_exit_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _command_app(CommandResult(text="bad", error=True, exit_code=2))

    with caplog.at_level("INFO", logger="punt_lux.cli._shared"):
        CliRunner().invoke(app, ["probe"], prog_name="lux")

    assert caplog.messages == ["CLI lux probe failed: exit 2"]


def test_the_resolved_identity_keeps_the_host_the_default_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = ClientIdentity(kind="cli", name="lux", host="pembroke")

    def _resolve(override: str | None = None) -> ClientIdentity:
        del override
        return declared

    monkeypatch.setattr(CliIdentity, "resolve", _resolve)

    identity = identity_from_flags(
        as_=None, kind=None, name="driver", repo=None, agent=None
    )

    assert identity.host == "pembroke"
