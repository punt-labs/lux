"""Unit tests for punt_lux.paths — socket discovery and process lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.paths import (
    cleanup_stale_socket,
    default_socket_path,
    ensure_display,
    is_display_running,
    pid_file_path,
    remove_pid_file,
    write_pid_file,
)


class TestDefaultSocketPath:
    def test_lux_socket_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUX_SOCKET", "/custom/path.sock")
        assert default_socket_path() == Path("/custom/path.sock")

    def test_xdg_runtime_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUX_SOCKET", raising=False)
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert default_socket_path() == Path("/run/user/1000/lux/display.sock")

    def test_fallback_tmp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUX_SOCKET", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("USER", "testuser")
        assert default_socket_path() == Path("/tmp/lux-testuser/display.sock")

    def test_env_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LUX_SOCKET takes precedence over XDG_RUNTIME_DIR."""
        monkeypatch.setenv("LUX_SOCKET", "/explicit.sock")
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert default_socket_path() == Path("/explicit.sock")


class TestPidFilePath:
    def test_suffix(self) -> None:
        assert pid_file_path(Path("/tmp/lux/display.sock")) == Path(
            "/tmp/lux/display.sock.pid"
        )


class TestIsDisplayRunning:
    def test_no_pid_file(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        assert not is_display_running(sock)

    def test_stale_pid(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        pid_path = tmp_path / "display.sock.pid"
        pid_path.write_text("999999999")
        assert not is_display_running(sock)

    def test_current_pid(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        pid_path = tmp_path / "display.sock.pid"
        pid_path.write_text(str(os.getpid()))
        assert is_display_running(sock)

    def test_corrupt_pid_file(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        pid_path = tmp_path / "display.sock.pid"
        pid_path.write_text("not_a_number")
        assert not is_display_running(sock)


class TestCleanupStaleSocket:
    def test_removes_stale_socket(self, tmp_path: Path) -> None:
        # Use a short path for the socket — macOS limits AF_UNIX to ~104 chars
        import socket
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        pid_path = sock_path.with_suffix(".sock.pid")

        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(str(sock_path))
            s.close()
            pid_path.write_text("999999999")

            cleanup_stale_socket(sock_path)

            assert not sock_path.exists()
            assert not pid_path.exists()
        finally:
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_preserves_non_socket_file(self, tmp_path: Path) -> None:
        sock_path = tmp_path / "display.sock"
        pid_path = tmp_path / "display.sock.pid"
        sock_path.touch()  # regular file, not a socket
        pid_path.write_text("999999999")

        cleanup_stale_socket(sock_path)

        assert sock_path.exists()  # not deleted — safety check
        assert not pid_path.exists()

    def test_preserves_running(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        pid_path = tmp_path / "display.sock.pid"
        sock.touch()
        pid_path.write_text(str(os.getpid()))

        cleanup_stale_socket(sock)

        assert sock.exists()
        assert pid_path.exists()


class TestWriteRemovePidFile:
    def test_roundtrip(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        write_pid_file(sock)
        pid_path = pid_file_path(sock)
        assert pid_path.exists()
        assert int(pid_path.read_text().strip()) == os.getpid()

        remove_pid_file(sock)
        assert not pid_path.exists()


class TestEnsureDisplay:
    def test_already_running(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"
        pid_path = tmp_path / "display.sock.pid"
        sock.touch()
        pid_path.write_text(str(os.getpid()))

        result = ensure_display(sock)
        assert result == sock

    def test_spawns_subprocess(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"

        def fake_popen(*args: object, **kwargs: object) -> object:
            # Simulate the display starting: create socket + PID file.
            sock.touch()
            pid_file_path(sock).write_text(str(os.getpid()))

            class FakeProc:
                pid = os.getpid()

            return FakeProc()

        with patch("punt_lux.paths.subprocess.Popen", side_effect=fake_popen):
            result = ensure_display(sock, timeout=2.0)

        assert result == sock

    def test_timeout_raises(self, tmp_path: Path) -> None:
        sock = tmp_path / "display.sock"

        class FakeProc:
            pid = 1

        with (
            patch("punt_lux.paths.subprocess.Popen", return_value=FakeProc()),
            pytest.raises(RuntimeError, match="failed to start"),
        ):
            ensure_display(sock, timeout=0.3)
