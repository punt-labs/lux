"""CLI-adapter tests for ``lux scene`` -- flag parsing, JSON payload handling,
and Ctx/scope wiring, with a stand-in sync-ops client (no real luxd).
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.operations import Cleared, OpError, SceneList, SceneShown

runner = CliRunner()


class _SceneClient:
    """A sync-ops stand-in recording calls and returning preset results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    @property
    def sync(self) -> _SceneClient:
        return self

    def render(self, request: object, *, scope: object = None) -> SceneShown:
        self.calls.append(("render", request))
        return SceneShown(scene_id=request.scene_id)  # type: ignore[attr-defined]

    def render_table(self, request: object, *, scope: object = None) -> SceneShown:
        self.calls.append(("render_table", request))
        return SceneShown(scene_id=request.scene_id)  # type: ignore[attr-defined]

    def clear_scene(self, scene_id: str, *, scope: object) -> Cleared:
        self.calls.append(("clear_scene", scene_id))
        return Cleared()

    def clear(self, *, scope: object) -> Cleared:
        self.calls.append(("clear", None))
        return Cleared()

    def list_scenes(self) -> SceneList | OpError:
        return SceneList(scenes=[], frames=[])


class TestSceneShow:
    def test_show_installs_a_scene_from_inline_json(self) -> None:
        client = _SceneClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(
                app,
                [
                    "scene",
                    "show",
                    "s1",
                    '{"elements": [{"kind": "text", "id": "t1", "content": "hi"}]}',
                ],
            )
        assert result.exit_code == 0
        assert "shown:s1" in result.output
        assert client.calls[0][0] == "render"

    def test_show_rejects_malformed_json_before_any_network_call(self) -> None:
        client = _SceneClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["scene", "show", "s1", "not-json"])
        assert result.exit_code != 0
        assert client.calls == []


class TestSceneClear:
    def test_clear_removes_one_scene(self) -> None:
        client = _SceneClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["scene", "clear", "s1"])
        assert result.exit_code == 0
        assert client.calls == [("clear_scene", "s1")]

    def test_clear_all_removes_every_scene(self) -> None:
        client = _SceneClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["scene", "clear-all"])
        assert result.exit_code == 0
        assert client.calls == [("clear", None)]


class TestSceneLs:
    def test_ls_reports_scene_count(self) -> None:
        client = _SceneClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["scene", "ls"])
        assert result.exit_code == 0
        assert "scenes:0" in result.output

    def test_ls_reports_a_transport_fault_not_a_crash(self) -> None:
        """Regression: list_scenes used to raise RuntimeError on an OpError
        instead of reaching the shared error envelope (Bugbot)."""

        class _FaultingSceneClient(_SceneClient):
            def list_scenes(self) -> OpError:
                return OpError(code="invalid_request", reason="stale port")

        client = _FaultingSceneClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["scene", "ls"])
        assert result.exit_code == 1
        assert "stale port" in result.output
