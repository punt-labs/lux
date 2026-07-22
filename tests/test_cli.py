"""Unit tests for punt_lux CLI entry points."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.paths import DisplayPaths

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
        pid_path.write_text(str(os.getpid()))

        # Liveness is a socket handshake, not a PID-file lookup; patch the
        # probe so the CLI wiring is exercised without a real display.
        with patch.object(DisplayPaths, "is_running", return_value=True):
            result = runner.invoke(app, ["status", "--socket", str(sock)])
        assert result.exit_code == 0
        assert "running" in result.output
        assert str(os.getpid()) in result.output

    def test_status_default_socket(self) -> None:
        """Without --socket, uses DisplayPaths default path."""
        with patch.object(
            DisplayPaths,
            "_default_path",
            return_value=Path("/nonexistent/display.sock"),
        ):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "not running" in result.output


class _PingClient:
    """A LuxRestClient stand-in returning one preset ping result.

    Records the display-leg wait the CLI forwards, so a test can prove the
    ``--timeout`` value rides through as the ping budget rather than only
    sizing the HTTP transport.
    """

    def __init__(self, result: object) -> None:
        self._result = result
        self.forwarded_wait: float | None = None

    def ping(self, wait: float) -> object:
        self.forwarded_wait = wait
        return self._result


class TestPing:
    def test_ping_reports_luxd_down(self) -> None:
        # Drive the real LuxRestClient.connect with no port file, so the CLI
        # surfaces the production message — including the actionable hint —
        # rather than a string the test supplied.
        with patch("punt_lux.hub_paths.HubPaths.read_port", return_value=None):
            result = runner.invoke(app, ["ping"])
        assert result.exit_code == 1
        # Failure lines go to stderr per CLI convention; stdout stays clean.
        assert "luxd is not running" in result.stderr
        assert "lux hub-install" in result.stderr

    def test_ping_reports_round_trip(self) -> None:
        from punt_lux.operations import Pong

        with patch(
            "punt_lux.rest_client.LuxRestClient.connect",
            return_value=_PingClient(Pong(rtt_seconds=0.012)),
        ):
            result = runner.invoke(app, ["ping"])
        assert result.exit_code == 0
        assert "pong rtt=0.012s" in result.stdout

    @pytest.mark.parametrize(
        ("code", "line"),
        [
            ("display_unavailable", "Display not running"),
            ("timeout", "timeout"),
            ("fault", "timeout"),
        ],
    )
    def test_ping_maps_op_error_to_a_status_line(self, code: str, line: str) -> None:
        # A down display reads "Display not running"; every other reachable-luxd
        # failure (timeout, fault) reads "timeout". Both exit 1.
        from punt_lux.operations import OpError

        with patch(
            "punt_lux.rest_client.LuxRestClient.connect",
            return_value=_PingClient(OpError(code=code, reason="x")),  # type: ignore[arg-type]  # code is a parametrized OpErrorCode literal
        ):
            result = runner.invoke(app, ["ping"])
        assert result.exit_code == 1
        assert line in result.stderr

    def test_ping_http_bound_sits_a_margin_above_the_display_leg(self) -> None:
        # With no --timeout the display leg is luxd's default budget; the HTTP
        # bound sits a fixed margin above it, so the transport never trips first
        # and the wait forwarded to the display leg is that same default.
        from punt_lux.__main__ import _PING_HTTP_MARGIN_SECONDS
        from punt_lux.display_client import DEFAULT_RECV_TIMEOUT
        from punt_lux.operations import Pong

        captured: dict[str, object] = {}

        def _capture(*, timeout: float) -> _PingClient:
            client = _PingClient(Pong(rtt_seconds=0.001))
            captured["http"] = timeout
            captured["client"] = client
            return client

        with patch("punt_lux.rest_client.LuxRestClient.connect", side_effect=_capture):
            result = runner.invoke(app, ["ping"])
        assert result.exit_code == 0
        client = captured["client"]
        assert isinstance(client, _PingClient)
        assert client.forwarded_wait == DEFAULT_RECV_TIMEOUT
        assert captured["http"] == DEFAULT_RECV_TIMEOUT + _PING_HTTP_MARGIN_SECONDS

    def test_ping_forwards_a_small_user_timeout_and_reports_timeout(self) -> None:
        # The finding: --timeout 1 used to still wait ~5s because the value only
        # sized the HTTP transport. Now 1s is the real display-leg budget; the
        # HTTP bound stays a margin above it (the layers cannot invert), a slow
        # display reads "timeout" — not "luxd is not running" — and the wait
        # forwarded to the display leg is genuinely 1s.
        from punt_lux.__main__ import _PING_HTTP_MARGIN_SECONDS
        from punt_lux.operations import OpError

        captured: dict[str, object] = {}

        def _capture(*, timeout: float) -> _PingClient:
            client = _PingClient(OpError(code="timeout", reason="slow display"))
            captured["http"] = timeout
            captured["client"] = client
            return client

        with patch("punt_lux.rest_client.LuxRestClient.connect", side_effect=_capture):
            result = runner.invoke(app, ["ping", "--timeout", "1"])
        assert result.exit_code == 1
        assert "timeout" in result.stderr
        assert "not running" not in result.stderr
        client = captured["client"]
        assert isinstance(client, _PingClient)
        assert client.forwarded_wait == 1.0
        assert captured["http"] == 1.0 + _PING_HTTP_MARGIN_SECONDS


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
