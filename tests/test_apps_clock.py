"""Tests for the Analog Clock applet."""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.apps.clock import CLOCK_SOURCE, render_clock
from punt_lux.ast_check import check_source
from punt_lux.display import DisplayServer
from punt_lux.runtime import CodeExecutor


class TestClockSource:
    """Verify CLOCK_SOURCE compiles and passes AST checks."""

    def test_source_compiles(self) -> None:
        executor = CodeExecutor(CLOCK_SOURCE)
        assert not executor.has_error, executor.error_message

    def test_ast_check_clean(self) -> None:
        warnings = check_source(CLOCK_SOURCE)
        assert warnings == []


class TestRenderClock:
    """Verify render_clock calls show_async with correct args."""

    def test_show_async_args(self) -> None:
        client = MagicMock()
        render_clock(client)

        client.show_async.assert_called_once()
        args, kwargs = client.show_async.call_args
        assert args[0] == "app-clock"  # scene_id
        elements = kwargs.get("elements", args[1] if len(args) > 1 else None)
        assert elements[0].source == CLOCK_SOURCE

    def test_frame_flags(self) -> None:
        client = MagicMock()
        render_clock(client)

        kwargs = client.show_async.call_args[1]
        flags = kwargs["frame_flags"]
        assert flags["no_title_bar"] is True
        assert flags["no_background"] is True
        assert flags["auto_resize"] is True
        assert flags["no_resize"] is True


class TestFlagMap:
    """Verify _FLAG_MAP contains new frame flag entries."""

    def test_no_title_bar(self) -> None:
        assert "no_title_bar" in DisplayServer._FLAG_MAP

    def test_no_background(self) -> None:
        assert "no_background" in DisplayServer._FLAG_MAP

    def test_no_scrollbar(self) -> None:
        assert "no_scrollbar" in DisplayServer._FLAG_MAP
