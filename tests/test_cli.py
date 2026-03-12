"""Unit tests for punt_lux CLI entry points."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
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
            result = runner.invoke(app, ["display"])
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(None, test_auto_click=False)
            mock_cls.return_value.run.assert_called_once()

    def test_display_with_socket(self) -> None:
        with patch("punt_lux.display.DisplayServer") as mock_cls:
            result = runner.invoke(app, ["display", "--socket", "/tmp/test.sock"])
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("/tmp/test.sock", test_auto_click=False)

    def test_display_with_test_auto_click(self) -> None:
        with patch("punt_lux.display.DisplayServer") as mock_cls:
            result = runner.invoke(app, ["display", "--test-auto-click"])
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(None, test_auto_click=True)


class TestDisplayMissingExtras:
    def test_display_missing_display_extra(self) -> None:
        """lux display exits 1 with helpful message when display deps missing."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "punt_lux.display":
                raise ModuleNotFoundError(name="imgui_bundle")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = runner.invoke(app, ["display"])

        assert result.exit_code == 1
        assert "Display extras not installed" in result.output

    def test_display_reraises_unrelated_import_error(self) -> None:
        """lux display re-raises ModuleNotFoundError for non-display modules."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "punt_lux.display":
                raise ModuleNotFoundError(name="some_unrelated_package")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = runner.invoke(app, ["display"])

        # Typer catches the unhandled exception — exit code 1 but no
        # "Display extras" message
        assert "Display extras not installed" not in result.output


class TestNoArgs:
    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # Typer returns exit code 0 or 2 for no_args_is_help depending on version
        assert result.exit_code in {0, 2}
        assert "display" in result.output.lower()
        assert "version" in result.output.lower()
        assert "status" in result.output.lower()
