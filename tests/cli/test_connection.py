"""Check the CLI-shaped Hub connection boundary."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import typer

from punt_lux.cli._connection import connect_client
from punt_lux.client.rest_transport import HubUnavailableError


def test_unavailable_hub_is_reported_as_a_cli_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "punt_lux.cli._connection.LuxClient.connect",
            side_effect=HubUnavailableError("Hub is not running"),
        ) as connect,
        pytest.raises(typer.Exit) as caught,
    ):
        connect_client(timeout=0.25)

    connect.assert_called_once_with(timeout=0.25)
    assert caught.value.exit_code == 1
    assert capsys.readouterr().err == "Hub is not running\n"


def test_a_ping_without_luxd_leaves_a_durable_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from typer.testing import CliRunner

    from punt_lux.__main__ import app

    with (
        patch(
            "punt_lux.cli._connection.LuxClient.connect",
            side_effect=HubUnavailableError("luxd is not running"),
        ),
        caplog.at_level("INFO", logger="punt_lux.cli._connection"),
    ):
        result = CliRunner().invoke(app, ["ping"])

    assert result.exit_code == 1
    assert caplog.messages == ["CLI lux ping failed: luxd unavailable"]


def test_a_command_path_outside_a_cli_run_is_the_program_name() -> None:
    from punt_lux.cli._connection import _click_command_path, command_path

    assert command_path() == "lux"
    assert _click_command_path() == "lux"
