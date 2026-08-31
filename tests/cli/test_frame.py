"""CLI-adapter tests for ``lux frame`` -- the raise and close verbs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.operations import FrameRaise, Ok, OpError

if TYPE_CHECKING:
    from punt_lux.operations import Scope

runner = CliRunner()


class _FrameClient:
    """Fake sync-ops FrameOps client -- one preset outcome per method."""

    def __init__(
        self,
        raise_result: FrameRaise | OpError | None = None,
        close_result: Ok | OpError | None = None,
    ) -> None:
        self._raise_result = raise_result
        self._close_result = close_result
        self.calls: list[tuple[str, str]] = []

    @property
    def sync(self) -> _FrameClient:
        return self

    def raise_frame(self, frame_id: str, *, scope: Scope) -> FrameRaise | OpError:
        del scope
        self.calls.append(("raise_frame", frame_id))
        assert self._raise_result is not None
        return self._raise_result

    def close_frame(self, frame_id: str) -> Ok | OpError:
        self.calls.append(("close_frame", frame_id))
        assert self._close_result is not None
        return self._close_result


class TestFrameRaise:
    def test_raise_brings_a_live_frame_to_the_front(self) -> None:
        client = _FrameClient(raise_result=FrameRaise(frame_id="f1", raised=True))
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["frame", "raise", "f1"])
        assert result.exit_code == 0
        assert client.calls == [("raise_frame", "f1")]

    def test_raise_reports_an_absent_frame_without_erroring(self) -> None:
        client = _FrameClient(raise_result=FrameRaise(frame_id="f1", raised=False))
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["frame", "raise", "f1"])
        assert result.exit_code == 0

    def test_raise_maps_display_unavailable_to_exit_1(self) -> None:
        client = _FrameClient(
            raise_result=OpError(code="display_unavailable", reason="down"),
        )
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["frame", "raise", "f1"])
        assert result.exit_code == 1


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
