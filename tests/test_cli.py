"""Unit tests for punt_lux CLI entry points."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app

runner = CliRunner()


class TestVersion:
    def test_version_output(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "lux " in result.output

    def test_version_contains_semver(self) -> None:
        result = runner.invoke(app, ["version"])
        # Output is "lux X.Y.Z" — version part has at least one dot
        version_str = result.output.strip().split(" ", 1)[1]
        assert "." in version_str


class TestStatus:
    def test_status_not_running(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        result = runner.invoke(app, ["status", "--socket", str(sock)])
        assert result.exit_code == 1
        assert "not running" in result.output

    def test_status_running(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        pid_path = tmp_path / "display.sock.pid"
        sock.touch()
        pid_path.write_text(str(os.getpid()))

        result = runner.invoke(app, ["status", "--socket", str(sock)])
        assert result.exit_code == 0
        assert "running" in result.output
        assert str(os.getpid()) in result.output

    def test_status_default_socket(self) -> None:
        """Without --socket, uses default_socket_path()."""
        with patch(
            "punt_lux.paths.default_socket_path",
            return_value=Path("/nonexistent/display.sock"),
        ):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "not running" in result.output


class TestDisplay:
    def test_display_calls_server(self) -> None:
        """display command constructs DisplayServer and calls run()."""
        with patch("punt_lux.display.DisplayServer") as mock_cls:
            runner.invoke(app, ["display"])
            mock_cls.assert_called_once_with(None)
            mock_cls.return_value.run.assert_called_once()

    def test_display_with_socket(self) -> None:
        with patch("punt_lux.display.DisplayServer") as mock_cls:
            runner.invoke(app, ["display", "--socket", "/tmp/test.sock"])
            mock_cls.assert_called_once_with("/tmp/test.sock")


class TestNoArgs:
    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # Typer returns exit code 0 or 2 for no_args_is_help depending on version
        assert result.exit_code in {0, 2}
        assert "display" in result.output.lower()
        assert "version" in result.output.lower()
        assert "status" in result.output.lower()
