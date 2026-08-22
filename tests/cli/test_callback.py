"""CLI-adapter test for ``lux callback register``."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.operations import Ok

runner = CliRunner()


class _CallbackClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def sync(self) -> _CallbackClient:
        return self

    def register_callback(self, callback_id: str, label: str) -> Ok:
        self.calls.append((callback_id, label))
        return Ok()


class TestCallbackRegister:
    def test_register_sends_the_callback_id_and_label(self) -> None:
        client = _CallbackClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["callback", "register", "beads", "Beads"])
        assert result.exit_code == 0
        assert "registered:beads" in result.output
        assert client.calls == [("beads", "Beads")]
