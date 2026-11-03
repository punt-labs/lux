"""CLI-adapter test for ``lux callback register``."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.cli.callback import _CallbackRegisterAdapter
from punt_lux.domain.ids import ConnectionId
from punt_lux.domain.scope import Scope
from punt_lux.operations import Ok
from punt_lux.operations.models.callback_fields import CallbackFields
from punt_lux.operations.models.callbacks import RegisterCallbackRequest

runner = CliRunner()
_SCOPE = Scope.in_process(ConnectionId("conn"))


class _CallbackClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    @property
    def sync(self) -> _CallbackClient:
        return self

    def register_callback(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> Ok:
        self.calls.append((callback_id, label, frame_id))
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
        assert client.calls == [("beads", "Beads", None)]


class TestRegisterAdapter:
    def test_adapter_forwards_the_frame_id_the_request_carries(self) -> None:
        request = RegisterCallbackRequest.parse(
            CallbackFields("beads", "Beads", "beads-lux")
        )
        client = _CallbackClient()
        result = _CallbackRegisterAdapter(client).register_callback(
            request, scope=_SCOPE
        )
        assert isinstance(result, Ok)
        assert client.calls == [("beads", "Beads", "beads-lux")]

    def test_adapter_returns_a_parse_error_without_calling_the_client(self) -> None:
        request = RegisterCallbackRequest.parse(CallbackFields("", "Beads"))
        client = _CallbackClient()
        result = _CallbackRegisterAdapter(client).register_callback(
            request, scope=_SCOPE
        )
        assert result is request
        assert client.calls == []
