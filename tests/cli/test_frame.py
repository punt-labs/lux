"""CLI-adapter tests for ``lux frame`` -- the close verb."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.operations import Ok, OpError

runner = CliRunner()


class _FrameClient:
    """Fake sync-ops FrameOps client -- one preset outcome for close."""

    def __init__(self, close_result: Ok | OpError | None = None) -> None:
        self._close_result = close_result
        self.calls: list[tuple[str, str]] = []

    @property
    def sync(self) -> _FrameClient:
        return self

    def close_frame(self, frame_id: str) -> Ok | OpError:
        self.calls.append(("close_frame", frame_id))
        assert self._close_result is not None
        return self._close_result


class TestFrameClose:
    def test_close_tears_down_a_frame(self) -> None:
        client = _FrameClient(close_result=Ok())
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["frame", "close", "f1"])
        assert result.exit_code == 0
        assert client.calls == [("close_frame", "f1")]

    def test_close_maps_display_unavailable_to_exit_1(self) -> None:
        client = _FrameClient(
            close_result=OpError(code="display_unavailable", reason="down"),
        )
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["frame", "close", "f1"])
        assert result.exit_code == 1
