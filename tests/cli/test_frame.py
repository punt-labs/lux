"""CLI-adapter tests for ``lux frame`` -- the remove verb."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.operations import Ok, OpError

runner = CliRunner()


class _FrameClient:
    """Fake sync-ops FrameOps client -- one preset outcome for remove."""

    def __init__(self, remove_result: Ok | OpError | None = None) -> None:
        self._remove_result = remove_result
        self.calls: list[tuple[str, str]] = []

    @property
    def sync(self) -> _FrameClient:
        return self

    def remove_frame(self, frame_id: str, *, scope: object) -> Ok | OpError:
        del scope  # the fake asserts routing by call args, not the scope value
        self.calls.append(("remove_frame", frame_id))
        assert self._remove_result is not None
        return self._remove_result


class TestFrameRemove:
    def test_remove_tears_down_a_frame(self) -> None:
        client = _FrameClient(remove_result=Ok())
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["frame", "remove", "f1"])
        assert result.exit_code == 0
        assert client.calls == [("remove_frame", "f1")]

    def test_remove_maps_display_unavailable_to_exit_1(self) -> None:
        client = _FrameClient(
            remove_result=OpError(code="display_unavailable", reason="down"),
        )
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["frame", "remove", "f1"])
        assert result.exit_code == 1
