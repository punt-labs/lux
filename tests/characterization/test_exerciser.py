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

    def test_missing_stub_spec_raises(self) -> None:
        # A scenario that forgets to declare client.show but calls show()
        # would silently see None ("timeout") on the old contract. With
        # F4 the stub raises so the missing declaration surfaces.
        with pytest.raises(ToolCallError, match="stub 'show' called"):
            ToolExerciser.call(
                "show",
                {"scene_id": "s1", "elements": []},
                {"display_running": True, "client": {}},
            )


class TestPassthroughAllowlist:
    def test_show_runs_without_declaring_setup_apps_side_effects(self) -> None:
        # _setup_apps calls declare_menu_item and on_event on first
        # _get_client(). Those two are in _PASSTHROUGH_METHODS so a
        # scenario that only declares the methods its tool actually uses
        # records cleanly — the constant-overhead side effects don't
        # need a spec entry.
        result = ToolExerciser.call(
            "show",
            {"scene_id": "s1", "elements": []},
            {
                "display_running": True,
                "client": {"show": {"return": {"scene_id": "s1", "ts": 1000.0}}},
            },
        )
        assert result == "ack:s1"

    def test_non_allowlisted_method_still_raises(self) -> None:
        # The allowlist is constrained — only declare_menu_item and
        # on_event pass through silently. Any other unstubbed method
        # still raises, so the F4 safety net survives the F4-style
        # exception.
        from .exerciser import _StubClient

        client = _StubClient({})
        with pytest.raises(ToolCallError, match="stub 'show' called"):
            client.show()


class TestToolExceptionPropagates:
    def test_invalid_mode_raises_value_error_not_tool_call_error(
        self, tmp_path: object
    ) -> None:
        # set_display_mode raises ValueError on bad input. The exerciser
        # must not wrap that — production code's traceback is what callers
        # need to see.
        import pytest as _pytest

        with _pytest.raises(ValueError, match="Invalid mode"):
            ToolExerciser.call(
                "set_display_mode",
                {"mode": "bogus", "repo": str(tmp_path)},  # pyright: ignore[reportUnknownArgumentType]
                {"display_running": False, "client": {}},
            )
