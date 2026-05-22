"""Unit tests for ``ToolExerciser``."""

from __future__ import annotations

import pytest

from .exerciser import ToolCallError, ToolExerciser


class TestResolve:
    def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ToolCallError, match="unknown tool"):
            ToolExerciser.call("not_a_tool", {}, {"display_running": False})


class TestDisplayMode:
    def test_returns_off_when_unset(self, tmp_path: object) -> None:
        path = tmp_path  # pyright: ignore[reportUnknownVariableType]
        result = ToolExerciser.call(
            "display_mode", {"repo": str(path)}, {"display_running": False}
        )
        assert result == "display:off"


class TestPing:
    def test_pong_with_rtt(self) -> None:
        result = ToolExerciser.call(
            "ping",
            {},
            {
                "display_running": True,
                "time": 1000.042,
                "client": {"ping": {"return": {"ts": 1000.0, "display_ts": 1000.005}}},
            },
        )
        assert result == "pong rtt=0.042s"

    def test_not_running(self) -> None:
        result = ToolExerciser.call("ping", {}, {"display_running": False})
        assert result == "not running"


class TestShow:
    def test_ack(self) -> None:
        result = ToolExerciser.call(
            "show",
            {
                "scene_id": "s1",
                "elements": [{"kind": "text", "id": "t1", "content": "hi"}],
            },
            {
                "display_running": True,
                "client": {"show": {"return": {"scene_id": "s1", "ts": 1000.0}}},
            },
        )
        assert result == "ack:s1"

    def test_timeout(self) -> None:
        result = ToolExerciser.call(
            "show",
            {
                "scene_id": "s1",
                "elements": [{"kind": "text", "id": "t1", "content": "hi"}],
            },
            {"display_running": True, "client": {"show": {"return": None}}},
        )
        assert result == "timeout"


class TestRaisesOnBadSetup:
    def test_setup_client_must_be_mapping(self) -> None:
        with pytest.raises(ToolCallError, match=r"setup\.client must be a mapping"):
            ToolExerciser.call("ping", {}, {"display_running": True, "client": 7})

    def test_unexpected_query_method_raises(self) -> None:
        # set_theme calls client.query("set_theme", ...). If the setup
        # spec advertises a different method, the stub raises rather than
        # silently returning the wrong result.
        with pytest.raises(ToolCallError, match="stub query called"):
            ToolExerciser.call(
                "set_theme",
                {"theme": "darcula"},
                {
                    "display_running": True,
                    "client": {"query": {"method": "get_theme", "result": {}}},
                },
            )
