"""CLI-adapter tests for ``lux frame`` and ``lux menu`` with a stand-in client."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.operations import MenuList, Ok

if TYPE_CHECKING:
    from punt_lux.operations import FrameStatePatch

runner = CliRunner()


class _FrameMenuClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.frame_calls: list[tuple[str, FrameStatePatch]] = []

    def set_frame_state(self, frame_id: str, patch: FrameStatePatch) -> Ok:
        self.frame_calls.append((frame_id, patch))
        return Ok()

    def list_menus(self) -> MenuList:
        return MenuList(menus=[])

    def set_menu(self, request: object) -> Ok:
        self.calls.append(("set_menu", request))
        return Ok()


class TestFrameSetState:
    def test_set_state_minimizes_a_frame(self) -> None:
        client = _FrameMenuClient()
        with patch("punt_lux.rest_client.LuxRestClient.connect", return_value=client):
            result = runner.invoke(app, ["frame", "set-state", "f1", "--minimized"])
        assert result.exit_code == 0
        frame_id, patch_obj = client.frame_calls[0]
        assert frame_id == "f1"
        assert patch_obj.minimized is True


class TestMenuLs:
    def test_ls_reports_menu_count(self) -> None:
        client = _FrameMenuClient()
        with patch("punt_lux.rest_client.LuxRestClient.connect", return_value=client):
            result = runner.invoke(app, ["menu", "ls"])
        assert result.exit_code == 0
        assert "menus:0" in result.output


class TestMenuSet:
    def test_set_replaces_the_menu_bar_from_inline_json(self) -> None:
        client = _FrameMenuClient()
        with patch("punt_lux.rest_client.LuxRestClient.connect", return_value=client):
            result = runner.invoke(
                app,
                ["menu", "set", '[{"id": "beads", "label": "Beads"}]'],
            )
        assert result.exit_code == 0
        assert client.calls[0][0] == "set_menu"

    def test_set_rejects_a_json_object_body_not_array(self) -> None:
        client = _FrameMenuClient()
        with patch("punt_lux.rest_client.LuxRestClient.connect", return_value=client):
            result = runner.invoke(app, ["menu", "set", '{"not": "an array"}'])
        assert result.exit_code != 0
        assert client.calls == []
