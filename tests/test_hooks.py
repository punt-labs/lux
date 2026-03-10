"""Tests for punt_lux.hooks — pure handler functions."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import patch

from punt_lux.hooks import handle_post_bash, handle_session_start


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


def _bash_data(cmd: str) -> dict[str, object]:
    """Build a PostToolUse Bash hook payload."""
    return {"tool_input": {"command": cmd}}


class TestHandlePostBash:
    """Tests for handle_post_bash — PostToolUse Bash hook handler."""

    def test_ignores_non_bd_command(self) -> None:
        with patch("punt_lux.hooks.subprocess") as mock_sub:
            handle_post_bash(_bash_data("git status"))
        mock_sub.Popen.assert_not_called()

    def test_ignores_empty_data(self) -> None:
        with patch("punt_lux.hooks.subprocess") as mock_sub:
            handle_post_bash({})
        mock_sub.Popen.assert_not_called()

    def test_ignores_bare_bd(self) -> None:
        with patch("punt_lux.hooks.subprocess") as mock_sub:
            handle_post_bash(_bash_data("bd"))
        mock_sub.Popen.assert_not_called()

    def test_fires_on_bd_ready(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(_bash_data("bd ready"))
        m_popen.assert_called_once()

    def test_fires_on_bd_list(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(_bash_data("bd list --status=open"))
        m_popen.assert_called_once()

    def test_bd_without_beads_dir_skips(
        self,
        tmp_path: Path,
    ) -> None:
        # git rev-parse succeeds but .beads/ does not exist
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(_bash_data("bd create --title=T"))
        m_popen.assert_not_called()

    def test_fires_on_bd_create(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(_bash_data("bd create --title=T"))
        m_popen.assert_called_once()
        args = m_popen.call_args[0][0]
        assert args == ["lux", "show", "beads"]

    def test_fires_on_bd_close(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(_bash_data("bd close lux-abc"))
        m_popen.assert_called_once()

    def test_fires_on_bd_update(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(
                _bash_data("bd update lux-abc --status=closed"),
            )
        m_popen.assert_called_once()

    def test_fires_on_bd_dep(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(_bash_data("bd dep add lux-a lux-b"))
        m_popen.assert_called_once()

    def test_fires_on_bd_sync(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(_bash_data("bd sync"))
        m_popen.assert_called_once()

    def test_fires_on_chained_bd_command(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / ".beads").mkdir()
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 0
            m_run.return_value.stdout = str(tmp_path) + "\n"
            handle_post_bash(
                _bash_data("echo hello && bd close lux-abc"),
            )
        m_popen.assert_called_once()

    def test_ignores_when_git_fails(self) -> None:
        mock_run = patch("punt_lux.hooks.subprocess.run")
        mock_popen = patch("punt_lux.hooks.subprocess.Popen")
        with mock_run as m_run, mock_popen as m_popen:
            m_run.return_value.returncode = 128
            handle_post_bash(_bash_data("bd create --title=T"))
        m_popen.assert_not_called()
