"""Tests for punt_lux.hooks — pure handler functions."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import patch

from punt_lux.hooks import handle_session_start


def _ctx(result: dict[str, object]) -> str:
    """Extract additionalContext from hook output."""
    hso = cast("dict[str, object]", result["hookSpecificOutput"])
    return cast("str", hso["additionalContext"])


class TestHandleSessionStart:
    def test_default_off(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start()
        assert "off" in _ctx(result)

    def test_display_on(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "y"\n---\n')
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start()
        assert "on" in _ctx(result)

    def test_display_off(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n')
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start()
        assert "off" in _ctx(result)

    def test_returns_valid_hook_structure(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start()
        hso = cast("dict[str, object]", result["hookSpecificOutput"])
        assert hso["hookEventName"] == "SessionStart"
        assert "additionalContext" in hso
