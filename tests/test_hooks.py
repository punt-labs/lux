"""Tests for punt_lux.hooks — pure handler functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from punt_lux.hooks import handle_session_start


class TestHandleSessionStart:
    def test_default_off(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start({})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "off" in ctx

    def test_display_on(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "y"\n---\n')
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start({})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "on" in ctx

    def test_display_off(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n')
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start({})
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "off" in ctx

    def test_returns_valid_hook_structure(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".lux" / "config.md"
        with patch("punt_lux.hooks.resolve_config_path", return_value=config_path):
            result = handle_session_start({})
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "additionalContext" in result["hookSpecificOutput"]
