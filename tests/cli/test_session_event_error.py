"""CLI-adapter tests for ``lux session``, ``lux event``, ``lux error``."""

from __future__ import annotations

import re
from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.lease_term import PermanentLease
from punt_lux.operations import (
    ClientList,
    Identified,
    OpError,
    RecentErrors,
    RecentEvents,
)
from punt_lux.operations.models.query_clients import HubClient

runner = CliRunner()

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_DRAWING = re.compile(r"[─-╿]")  # rich panel borders: ─│╭╮╰╯


def _plain_text(output: str) -> str:
    """Strip ANSI color codes, rich panel borders, and collapse wrapping.

    Rich's error panel wraps at the console width -- which CI and a local
    terminal do not agree on -- so a substring spanning a wrap point (e.g.
    "value: --kind") can land on two separate, border-framed lines.
    Stripping the box-drawing border glyphs and collapsing all whitespace
    to single spaces makes a substring assertion robust to whatever width
    the panel happened to wrap at.
    """
    stripped = _BOX_DRAWING.sub("", _ANSI_ESCAPE.sub("", output))
    return " ".join(stripped.split())


_IDENTITY = ClientIdentity(kind="cli", name="mdm-test")


class _SessionClient:
    @property
    def sync(self) -> _SessionClient:
        return self

    def list_clients(self) -> ClientList:
        return ClientList(
            clients=[
                HubClient(
                    connection_id="c1",
                    identity=_IDENTITY,
                    connected_seconds=1.0,
                    lease=PermanentLease(),
                    subscribed_topics=[],
                    owned_scenes=[],
                )
            ]
        )

    def identify(self, declaration: dict[str, object], *, scope: object) -> Identified:
        return Identified(identity=_IDENTITY)


class _FaultingSessionClient:
    @property
    def sync(self) -> _FaultingSessionClient:
        return self

    def list_clients(self) -> OpError:
        return OpError(code="invalid_request", reason="stale port")

    def identify(self, declaration: dict[str, object], *, scope: object) -> Identified:
        return Identified(identity=_IDENTITY)


class _EventErrorClient:
    @property
    def sync(self) -> _EventErrorClient:
        return self

    def list_recent_events(self, count: int) -> RecentEvents:
        return RecentEvents(events=[], total_buffered=0)

    def list_errors(self, count: int) -> RecentErrors:
        return RecentErrors(errors=[], total_buffered=0)


class TestSessionLs:
    def test_ls_reports_session_count(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "ls"])
        assert result.exit_code == 0
        assert "sessions:1" in result.output

    def test_inspect_finds_a_known_connection(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "inspect", "c1"])
        assert result.exit_code == 0
        assert "c1" in result.output

    def test_inspect_reports_an_unknown_connection(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "inspect", "nope"])
        assert result.exit_code == 1

    def test_ls_reports_a_transport_fault_not_a_crash(self) -> None:
        """Regression: list_clients used to raise RuntimeError on an OpError
        instead of reaching the shared error envelope (Bugbot)."""
        client = _FaultingSessionClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "ls"])
        assert result.exit_code == 1
        assert "stale port" in result.output

    def test_inspect_reports_a_transport_fault_not_a_crash(self) -> None:
        client = _FaultingSessionClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "inspect", "c1"])
        assert result.exit_code == 1
        assert "stale port" in result.output


class TestSessionIdentify:
    def test_identify_declares_the_callers_identity(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(
                app, ["session", "identify", "--kind", "cli", "--name", "mdm-test"]
            )
        assert result.exit_code == 0

    def test_identify_rejects_an_invalid_kind_as_a_usage_error(self) -> None:
        """Regression: an invalid --kind used to crash with an unhandled
        pydantic ValidationError instead of a usage error (Bugbot MEDIUM)."""
        result = runner.invoke(
            app, ["session", "identify", "--kind", "bogus", "--name", "mdm-test"]
        )
        assert result.exit_code == 2
        assert "Invalid value: --kind" in _plain_text(result.output)


class TestEventErrorLs:
    def test_event_ls_reports_zero_events(self) -> None:
        client = _EventErrorClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["event", "ls"])
        assert result.exit_code == 0

    def test_error_ls_reports_zero_errors(self) -> None:
        client = _EventErrorClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["error", "ls"])
        assert result.exit_code == 0
