"""Check the CLI-shaped Hub connection boundary."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import typer

from punt_lux.cli._connection import connect_client
from punt_lux.rest_transport import HubUnavailableError


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
