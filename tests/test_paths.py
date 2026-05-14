"""Unit tests for punt_lux.paths — DisplayPaths class."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.paths import DisplayPaths


class TestDefaultPath:
    def test_lux_socket_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUX_SOCKET", "/custom/path.sock")
        assert DisplayPaths._default_path() == Path("/custom/path.sock")

    def test_xdg_runtime_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUX_SOCKET", raising=False)
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert DisplayPaths._default_path() == Path("/run/user/1000/lux/display.sock")

    def test_fallback_tmp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUX_SOCKET", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("USER", "testuser")
        assert DisplayPaths._default_path() == Path("/tmp/lux-testuser/display.sock")

    def test_env_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LUX_SOCKET takes precedence over XDG_RUNTIME_DIR."""
        monkeypatch.setenv("LUX_SOCKET", "/explicit.sock")
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert DisplayPaths._default_path() == Path("/explicit.sock")


class TestConstructor:
    def test_explicit_path(self) -> None:
        dp = DisplayPaths(Path("/tmp/custom.sock"))
        assert dp.socket_path == Path("/tmp/custom.sock")

    def test_default_path_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUX_SOCKET", "/env.sock")
        dp = DisplayPaths()
        assert dp.socket_path == Path("/env.sock")


class TestProperties:
    def test_pid_path(self) -> None:
        dp = DisplayPaths(Path("/tmp/lux/display.sock"))
        assert dp.pid_path == Path("/tmp/lux/display.sock.pid")

    def test_log_path(self) -> None:
        dp = DisplayPaths(Path("/tmp/lux/display.sock"))
        assert dp.log_path == Path("/tmp/lux/display.sock.log")


class TestIsRunning:
    def test_no_pid_file(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        assert not dp.is_running()

    def test_stale_pid(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.pid_path.write_text("999999999")
        assert not dp.is_running()

    def test_current_pid(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.pid_path.write_text(str(os.getpid()))
        assert dp.is_running()

    def test_corrupt_pid_file(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.pid_path.write_text("not_a_number")
        assert not dp.is_running()


class TestCleanupStale:
    def test_removes_stale_socket(self, tmp_path: Path) -> None:
        import socket
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        dp = DisplayPaths(sock_path)

        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(str(sock_path))
            s.close()
            dp.pid_path.write_text("999999999")

            dp.cleanup_stale()

            assert not sock_path.exists()
            assert not dp.pid_path.exists()
        finally:
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_preserves_non_socket_file(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.socket_path.touch()
        dp.pid_path.write_text("999999999")

        dp.cleanup_stale()

        assert dp.socket_path.exists()
        assert not dp.pid_path.exists()

    def test_preserves_running(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.socket_path.touch()
        dp.pid_path.write_text(str(os.getpid()))

        dp.cleanup_stale()

        assert dp.socket_path.exists()
        assert dp.pid_path.exists()


class TestWriteRemovePid:
    def test_roundtrip(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.write_pid()
        assert dp.pid_path.exists()
        assert int(dp.pid_path.read_text().strip()) == os.getpid()

        dp.remove_pid()
        assert not dp.pid_path.exists()


class TestEnsure:
    def test_already_running(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.socket_path.touch()
        dp.pid_path.write_text(str(os.getpid()))

        result = dp.ensure()
        assert result == dp.socket_path

    def test_spawns_subprocess(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")

        def fake_popen(*args: object, **kwargs: object) -> object:
            dp.socket_path.touch()
            dp.pid_path.write_text(str(os.getpid()))

            class FakeProc:
                pid = os.getpid()

            return FakeProc()

        with patch("punt_lux.paths.subprocess.Popen", side_effect=fake_popen):
            result = dp.ensure(timeout=2.0)

        assert result == dp.socket_path

    def test_timeout_raises(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")

        class FakeProc:
            pid = 1

        with (
            patch("punt_lux.paths.subprocess.Popen", return_value=FakeProc()),
            pytest.raises(RuntimeError, match="failed to start"),
        ):
            dp.ensure(timeout=0.3)
