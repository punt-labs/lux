"""Tests for punt_lux.hooks — pure handler functions."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.config import LuxConfig
from punt_lux.hooks import handle_session_start

_DISPLAY_ON = LuxConfig(display="y")
_DISPLAY_OFF = LuxConfig(display="n")


def _mock_config_manager(cfg: LuxConfig) -> MagicMock:
    """Build a mock ConfigManager whose read() returns *cfg*."""
    mgr = MagicMock()
    mgr.read.return_value = cfg
    return MagicMock(return_value=mgr)


def _ctx(result: dict[str, object]) -> str:
    """Extract additionalContext from hook output."""
    hso = cast("dict[str, object]", result["hookSpecificOutput"])
    return cast("str", hso["additionalContext"])


class TestHandleSessionStart:
    @pytest.mark.parametrize(
        ("cfg", "decision"), [(_DISPLAY_ON, "enabled"), (_DISPLAY_OFF, "disabled")]
    )
    def test_logs_display_decision(
        self, caplog: pytest.LogCaptureFixture, cfg: LuxConfig, decision: str
    ) -> None:
        with (
            caplog.at_level(logging.INFO),
            patch("punt_lux.session_start.ConfigManager", _mock_config_manager(cfg)),
        ):
            handle_session_start()
        assert caplog.messages == [f"SessionStart display decision: {decision}"]

    def test_logs_safe_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        with (
            patch(
                "punt_lux.session_start.ConfigManager",
                side_effect=OSError("/private/alice"),
            ),
            pytest.raises(OSError),
        ):
            handle_session_start()
        assert caplog.messages == ["SessionStart display decision failed: OSError"]

    def test_default_off(self) -> None:
        mock_cls = _mock_config_manager(_DISPLAY_OFF)
        with patch("punt_lux.session_start.ConfigManager", mock_cls):
            result = handle_session_start()
        assert "off" in _ctx(result)

    def test_display_on(self) -> None:
        mock_cls = _mock_config_manager(_DISPLAY_ON)
        with patch("punt_lux.session_start.ConfigManager", mock_cls):
            result = handle_session_start()
        assert "on" in _ctx(result)

    def test_display_on_says_the_menu_is_not_the_agents_job(self) -> None:
        # The session's own server registers and services its menu entries, so the
        # context tells the agent what not to do: registering over MCP would be
        # refused (no listen leg on that connection) and polling would only add
        # latency to a path that has none.
        mock_cls = _mock_config_manager(_DISPLAY_ON)
        with patch("punt_lux.session_start.ConfigManager", mock_cls):
            ctx = _ctx(handle_session_start())
        assert "applets" in ctx
        assert "do not register menu callbacks" in ctx
        assert "do not poll for clicks" in ctx

    def test_display_on_points_at_the_skill_for_the_board(self) -> None:
        # The board itself is still the agent's to build when asked for it.
        mock_cls = _mock_config_manager(_DISPLAY_ON)
        with patch("punt_lux.session_start.ConfigManager", mock_cls):
            ctx = _ctx(handle_session_start())
        assert "/lux:scene.beads" in ctx

    def test_display_off_says_nothing_about_menus(self) -> None:
        mock_cls = _mock_config_manager(_DISPLAY_OFF)
        with patch("punt_lux.session_start.ConfigManager", mock_cls):
            ctx = _ctx(handle_session_start())
        assert "menu" not in ctx

    def test_display_off(self) -> None:
        mock_cls = _mock_config_manager(_DISPLAY_OFF)
        with patch("punt_lux.session_start.ConfigManager", mock_cls):
            result = handle_session_start()
        assert "off" in _ctx(result)

    def test_returns_valid_hook_structure(self) -> None:
        mock_cls = _mock_config_manager(_DISPLAY_OFF)
        with patch("punt_lux.session_start.ConfigManager", mock_cls):
            result = handle_session_start()
        hso = cast("dict[str, object]", result["hookSpecificOutput"])
        assert hso["hookEventName"] == "SessionStart"
        assert "additionalContext" in hso
