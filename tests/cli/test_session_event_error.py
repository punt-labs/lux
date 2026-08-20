"""CLI-adapter tests for ``lux session``, ``lux event``, ``lux error``."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.lease_term import PermanentLease
from punt_lux.operations import ClientList, Identified, RecentErrors, RecentEvents
from punt_lux.operations.models.query_clients import HubClient

runner = CliRunner()

_IDENTITY = ClientIdentity(kind="cli", name="mdm-test")


class _SessionClient:
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


class _EventErrorClient:
    def list_recent_events(self, count: int) -> RecentEvents:
        return RecentEvents(events=[], total_buffered=0)

    def list_errors(self, count: int) -> RecentErrors:
        return RecentErrors(errors=[], total_buffered=0)


class TestSessionLs:
    def test_ls_reports_session_count(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "ls"])
        assert result.exit_code == 0
        assert "sessions:1" in result.output

    def test_inspect_finds_a_known_connection(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "inspect", "c1"])
        assert result.exit_code == 0
        assert "c1" in result.output

    def test_inspect_reports_an_unknown_connection(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["session", "inspect", "nope"])
        assert result.exit_code == 1


class TestSessionIdentify:
    def test_identify_declares_the_callers_identity(self) -> None:
        client = _SessionClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(
                app, ["session", "identify", "--kind", "cli", "--name", "mdm-test"]
            )
        assert result.exit_code == 0


class TestEventErrorLs:
    def test_event_ls_reports_zero_events(self) -> None:
        client = _EventErrorClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["event", "ls"])
        assert result.exit_code == 0

    def test_error_ls_reports_zero_errors(self) -> None:
        client = _EventErrorClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["error", "ls"])
        assert result.exit_code == 0
