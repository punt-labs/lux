"""Unit tests for punt_lux.paths — DisplayPaths class.

The socket is authoritative for both liveness and identity. A connection
that is accepted proves a live owner — even with a slow or missing
handshake — so an accepting socket is never spawned over nor unlinked.
Identity for reaping is the socket's OS peer credential, never a PID
file. These tests stand up real listening Unix sockets to exercise the
singleton guard, cleanup, spawn idempotency, and reaping.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest

from punt_lux.paths import DisplayPaths, SocketLiveness, is_hub_running
from punt_lux.protocol import HEADER_FORMAT, ReadyMessage, encode_frame, send_message

_Reply = Literal["ready", "silent", "garbage", "nonobject"]


def _frame_json(value: object) -> bytes:
    """Frame an arbitrary JSON value (including non-objects) as a wire frame."""
    data = json.dumps(value).encode()
    return struct.pack(HEADER_FORMAT, len(data)) + data


class _FakeDisplay:
    """A minimal listening socket standing in for a live display server.

    Binds the socket and accepts connections on a background thread. Each
    accepted connection is answered per ``reply``: a ``ReadyMessage``
    (``"ready"``), nothing (``"silent"`` — accepts but never handshakes),
    or a present-but-malformed frame (``"garbage"``).
    """

    _path: Path
    _sock: socket.socket
    _thread: threading.Thread
    _stop: threading.Event
    _reply: _Reply

    def __new__(
        cls, path: Path, *, answer: bool = True, reply: _Reply | None = None
    ) -> _FakeDisplay:
        self = super().__new__(cls)
        self._path = path
        self._reply = reply if reply is not None else ("ready" if answer else "silent")
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(path))
        self._sock.listen(5)
        self._sock.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            with contextlib.suppress(OSError):
                if self._reply == "ready":
                    send_message(conn, ReadyMessage())
                elif self._reply == "garbage":
                    conn.sendall(encode_frame({"no_type_field": 1}))
                elif self._reply == "nonobject":
                    conn.sendall(_frame_json(42))  # valid JSON, not an object
            conn.close()

    def stop(self) -> None:
        """Stop serving and close the listening socket."""
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()


def _short_socket() -> Path:
    """Return a fresh short socket path (macOS AF_UNIX 104-char limit)."""
    return Path(tempfile.mkdtemp(prefix="lux-")) / "d.sock"


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
    """Liveness is a socket handshake, not a PID-file lookup."""

    def test_no_socket_file(self) -> None:
        dp = DisplayPaths(_short_socket())
        assert not dp.is_running()

    def test_live_server_answers(self) -> None:
        path = _short_socket()
        display = _FakeDisplay(path)
        try:
            assert DisplayPaths(path).is_running()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_stale_socket_no_listener(self) -> None:
        """A socket file with no listener is dead (connection refused)."""
        path = _short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # leaves the file, but nothing is listening
        try:
            assert not DisplayPaths(path).is_running()
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_recycled_pid_is_not_alive(self) -> None:
        """A PID file naming a live unrelated process must not read as alive.

        The PID file records this test process (very much alive), but no
        server listens on the socket. Trusting the PID would be a false
        positive; the socket probe correctly reports dead.
        """
        path = _short_socket()
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        try:
            assert not dp.is_running()
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_bound_socket_without_handshake_is_alive(self) -> None:
        """A process that accepts a connection owns the socket, handshake or not.

        A live-but-slow display (mid-render, breakpoint, slow GPU) accepts
        the connection but may miss the handshake window. Acceptance alone
        proves a live owner: it must read as running so it is never spawned
        over nor unlinked.
        """
        path = _short_socket()
        display = _FakeDisplay(path, answer=False)
        try:
            assert DisplayPaths(path).is_running()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_probe_distinguishes_accepting_from_ready(self) -> None:
        """_probe reports READY on handshake, ACCEPTING on a silent listener."""
        ready_path = _short_socket()
        ready = _FakeDisplay(ready_path)
        silent_path = _short_socket()
        silent = _FakeDisplay(silent_path, answer=False)
        try:
            assert DisplayPaths(ready_path)._probe() is SocketLiveness.READY
            assert DisplayPaths(silent_path)._probe() is SocketLiveness.ACCEPTING
        finally:
            ready.stop()
            silent.stop()
            shutil.rmtree(ready_path.parent, ignore_errors=True)
            shutil.rmtree(silent_path.parent, ignore_errors=True)

    def test_probe_refused_socket_is_dead(self) -> None:
        """_probe reports DEAD when the file exists but nothing listens."""
        path = _short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()
        try:
            assert DisplayPaths(path)._probe() is SocketLiveness.DEAD
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_probe_malformed_frame_is_accepting(self) -> None:
        """A live owner answering with a malformed first frame reads ACCEPTING.

        A present-but-undecodable frame proves a live owner answered, so it
        must not crash the probe nor read as dead.
        """
        path = _short_socket()
        display = _FakeDisplay(path, reply="garbage")
        try:
            assert DisplayPaths(path)._probe() is SocketLiveness.ACCEPTING
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_probe_nonobject_payload_is_accepting(self) -> None:
        """A live owner replying with a JSON non-object does not crash the probe.

        A valid frame whose JSON payload is ``42`` (not an object) makes the
        decoder's ``d.get("type")`` raise AttributeError. Connect already
        proved a live owner, so the probe must read ACCEPTING — not let the
        exception escape and crash is_running().
        """
        path = _short_socket()
        display = _FakeDisplay(path, reply="nonobject")
        try:
            dp = DisplayPaths(path)
            assert dp._probe() is SocketLiveness.ACCEPTING
            assert dp.is_running() is True  # never raised
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_probe_connect_timeout_is_accepting_and_preserves_socket(self) -> None:
        """A connect that times out is a live-but-overloaded owner → ACCEPTING.

        settimeout applies to connect() too; a slow owner whose connect
        can't complete in the probe window must read ACCEPTING (presence
        wins), and cleanup_stale must never unlink its socket.
        """
        path = _short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # socket file exists; connect is what we force to time out
        dp = DisplayPaths(path)
        try:
            with patch("socket.socket.connect", side_effect=TimeoutError):
                assert dp._probe() is SocketLiveness.ACCEPTING
                dp.cleanup_stale()  # must not unlink a possibly-live socket
            assert path.exists()
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)


class TestCleanupStale:
    def test_removes_dead_socket(self) -> None:
        path = _short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()
        dp = DisplayPaths(path)
        dp.pid_path.write_text("999999999")
        try:
            dp.cleanup_stale()
            assert not path.exists()
            assert not dp.pid_path.exists()
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_preserves_live_socket(self) -> None:
        """A live display's socket and PID file are never removed."""
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        try:
            dp.cleanup_stale()
            assert path.exists()
            assert dp.pid_path.exists()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_preserves_non_socket_file(self) -> None:
        path = _short_socket()
        path.write_text("not a socket")
        dp = DisplayPaths(path)
        dp.pid_path.write_text("999999999")
        try:
            dp.cleanup_stale()
            assert path.exists()  # regular file, not a socket — left intact
            assert not dp.pid_path.exists()
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_preserves_accepting_but_silent_socket(self) -> None:
        """A live-but-slow display's socket is never unlinked on a missing handshake.

        The socket accepts the connection but sends no ReadyMessage within
        the probe window. Unlinking it would orphan the live owner and let
        the next spawn stack a second window — the exact bug the accepting
        invariant closes.
        """
        path = _short_socket()
        display = _FakeDisplay(path, answer=False)
        dp = DisplayPaths(path)
        try:
            dp.cleanup_stale()
            assert path.exists()  # accepting socket preserved, owner not orphaned
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)


class TestWriteRemovePid:
    def test_roundtrip(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.write_pid()
        assert dp.pid_path.exists()
        assert int(dp.pid_path.read_text().strip()) == os.getpid()

        dp.remove_pid()
        assert not dp.pid_path.exists()


class TestEnsure:
    def test_already_running_reuses(self) -> None:
        """A live display is reused — ensure() does not spawn."""
        path = _short_socket()
        display = _FakeDisplay(path)
        try:
            with patch("punt_lux.paths.subprocess.Popen") as popen:
                result = DisplayPaths(path).ensure()
            assert result == path
            popen.assert_not_called()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_idempotent_second_ensure_does_not_spawn(self) -> None:
        """Once a display answers, a second ensure() reuses it with no spawn."""
        path = _short_socket()
        display = _FakeDisplay(path)
        try:
            dp = DisplayPaths(path)
            with patch("punt_lux.paths.subprocess.Popen") as popen:
                dp.ensure()
                dp.ensure()
            popen.assert_not_called()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_stale_pid_file_preserves_live_socket(self) -> None:
        """The core regression: a live display with a missing/stale PID file.

        Remove the PID file while the display is alive. ensure() must NOT
        unlink the live socket and must NOT spawn a second process — it
        reuses the live server confirmed by the handshake.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        try:
            dp = DisplayPaths(path)
            dp.remove_pid()  # PID file absent, but the display is alive
            with patch("punt_lux.paths.subprocess.Popen") as popen:
                result = dp.ensure()
            assert result == path
            assert path.exists()  # live socket preserved
            popen.assert_not_called()  # no second display spawned
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_does_not_spawn_over_accepting_socket(self) -> None:
        """A live-but-slow display is reused, never duplicated.

        The socket accepts the connection but the handshake is absent, so a
        handshake-only liveness check would spawn a second window. ensure()
        reuses the accepting owner and never calls Popen.
        """
        path = _short_socket()
        display = _FakeDisplay(path, answer=False)
        try:
            with patch("punt_lux.paths.subprocess.Popen") as popen:
                result = DisplayPaths(path).ensure()
            assert result == path
            popen.assert_not_called()  # no duplicate window spawned
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_spawns_when_dead(self) -> None:
        path = _short_socket()
        dp = DisplayPaths(path)

        def fake_popen(*_args: object, **_kwargs: object) -> object:
            _FakeDisplay(path)

            class FakeProc:
                pid = os.getpid()

            return FakeProc()

        try:
            with patch(
                "punt_lux.paths.subprocess.Popen", side_effect=fake_popen
            ) as popen:
                result = dp.ensure(timeout=2.0)
            assert result == path
            popen.assert_called_once()
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_timeout_raises(self) -> None:
        path = _short_socket()
        dp = DisplayPaths(path)

        class FakeProc:
            pid = 1

        try:
            with (
                patch("punt_lux.paths.subprocess.Popen", return_value=FakeProc()),
                pytest.raises(RuntimeError, match="failed to start"),
            ):
                dp.ensure(timeout=0.3)
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_concurrent_ensure_spawns_once(self) -> None:
        """Two near-simultaneous ensure() calls spawn exactly one display.

        The spawn lock serializes the callers; the first spawns a display,
        the second observes it on the re-check and reuses it.
        """
        path = _short_socket()
        spawn_count = 0
        lock = threading.Lock()

        def fake_popen(*_args: object, **_kwargs: object) -> object:
            nonlocal spawn_count
            with lock:
                spawn_count += 1
            _FakeDisplay(path)

            class FakeProc:
                pid = os.getpid()

            return FakeProc()

        results: list[Path] = []

        def worker() -> None:
            results.append(DisplayPaths(path).ensure(timeout=3.0))

        try:
            with patch("punt_lux.paths.subprocess.Popen", side_effect=fake_popen):
                threads = [threading.Thread(target=worker) for _ in range(2)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=5)
            assert spawn_count == 1
            assert results == [path, path]
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)


class TestPeerPid:
    """The socket's OS peer credential resolves the true owner PID."""

    def test_live_socket_returns_owner_pid(self) -> None:
        """A live listener's peer credential names its owning process."""
        path = _short_socket()
        display = _FakeDisplay(path)
        try:
            # The FakeDisplay binds in this process, so it owns the socket.
            assert DisplayPaths(path)._peer_pid() == os.getpid()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_dead_socket_returns_none(self) -> None:
        """A stale socket with no listener yields no peer (connection refused)."""
        path = _short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # file remains, nothing listens
        try:
            assert DisplayPaths(path)._peer_pid() is None
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_unsupported_platform_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A platform without a peer-credential option yields None."""
        path = _short_socket()
        display = _FakeDisplay(path)
        monkeypatch.setattr("punt_lux.paths.sys.platform", "sunos5")
        try:
            assert DisplayPaths(path)._peer_pid() is None
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_non_positive_credential_returns_none(self) -> None:
        """A zeroed/partial credential (pid 0) resolves to None, never a target.

        os.kill(0, ...) signals the whole process group; a non-positive
        peer PID must never leave _peer_pid as a signallable value.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        try:
            with patch("socket.socket.getsockopt", return_value=b"\x00\x00\x00\x00"):
                assert DisplayPaths(path)._peer_pid() is None
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)


class TestReap:
    def test_reap_dead_clears_files_without_kill(self) -> None:
        """A stale/recycled PID is never signalled when the socket is dead."""
        path = _short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        try:
            with patch("punt_lux.paths.os.kill") as kill:
                dp.reap()
            kill.assert_not_called()  # recycled-PID friendly-fire avoided
            assert not path.exists()
            assert not dp.pid_path.exists()
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_live_terminates_owner(self) -> None:
        """A live display is terminated via its socket owner, then cleaned.

        The ``_FakeDisplay`` binds in this process, so the socket's peer
        credential and the recorded PID file agree on this test's PID.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        terminated: list[int] = []

        def fake_kill(pid: int, sig: int) -> None:
            if sig == 0:
                # First liveness re-check: still alive. After termination
                # is recorded, report the process as gone.
                if terminated:
                    raise ProcessLookupError
                return
            terminated.append(pid)
            display.stop()  # simulate the display exiting on SIGTERM

        try:
            with patch("punt_lux.paths.os.kill", side_effect=fake_kill):
                dp.reap(timeout=2.0)
            assert terminated == [os.getpid()]
            assert not path.exists()
            assert not dp.pid_path.exists()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_live_without_pid_uses_socket_owner(self) -> None:
        """A live display with NO PID file is still reaped via the socket.

        The round-2 gap: identity comes from the socket's OS peer
        credential, not the PID file. reap() resolves the true owner
        with getsockopt and terminates it, then clears the dead socket —
        so a restart spawns exactly one display instead of orphaning the
        old one and stacking a second window.

        The ``_FakeDisplay`` binds in this process, so the resolved owner
        is this test's own PID; ``os.kill`` is patched so the SIGTERM is
        observed, not delivered.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)  # no PID file written
        terminated: list[int] = []

        def fake_kill(pid: int, sig: int) -> None:
            if sig == 0:
                if terminated:
                    raise ProcessLookupError
                return
            terminated.append(pid)
            display.stop()  # simulate the display exiting on SIGTERM

        try:
            with patch("punt_lux.paths.os.kill", side_effect=fake_kill):
                dp.reap(timeout=2.0)
            assert terminated == [os.getpid()]  # resolved via peer-pid, not file
            assert not path.exists()  # dead socket cleared → restart spawns one
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_live_prefers_socket_owner_over_stale_pid(self) -> None:
        """A divergent PID file does not misdirect the kill.

        With a live display and a PID file naming a different, unrelated
        PID, reap() must signal the socket's true owner (this process),
        never the stale file value — the socket wins on identity.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        dp.pid_path.write_text("4242")  # stale/divergent — must be ignored
        terminated: list[int] = []

        def fake_kill(pid: int, sig: int) -> None:
            if sig == 0:
                if terminated:
                    raise ProcessLookupError
                return
            terminated.append(pid)
            display.stop()

        try:
            with patch("punt_lux.paths.os.kill", side_effect=fake_kill):
                dp.reap(timeout=2.0)
            assert terminated == [os.getpid()]  # peer-pid beats the stale file
            assert not path.exists()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_terminates_accepting_but_silent_owner(self) -> None:
        """A live-but-slow display is reaped via its owner, not unlink-only.

        The socket accepts but never handshakes. reap() must resolve the
        owner via the peer credential and terminate it — never silently
        unlink the socket while leaving the process running.
        """
        path = _short_socket()
        display = _FakeDisplay(path, answer=False)
        dp = DisplayPaths(path)
        terminated: list[int] = []

        def fake_kill(pid: int, sig: int) -> None:
            if sig == 0:
                if terminated:
                    raise ProcessLookupError
                return
            terminated.append(pid)
            display.stop()

        try:
            with patch("punt_lux.paths.os.kill", side_effect=fake_kill):
                dp.reap(timeout=2.0)
            assert terminated == [os.getpid()]  # owner resolved and terminated
            assert not path.exists()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_raises_when_owner_survives_termination(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reap() raises so the caller (make restart) does not spawn over a survivor.

        The owner ignores SIGTERM and SIGKILL — os.kill(pid, 0) keeps
        reporting it alive. reap() must raise rather than clear files and
        let a second display spawn atop the still-held socket.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        monkeypatch.setattr("punt_lux.paths._SIGKILL_GRACE", 0.2)

        def stubborn_kill(_pid: int, _sig: int) -> None:
            return  # every signal ignored; the process never exits

        try:
            with (
                patch("punt_lux.paths.os.kill", side_effect=stubborn_kill),
                pytest.raises(RuntimeError, match="survived SIGKILL"),
            ):
                dp.reap(timeout=0.2)
            assert path.exists()  # live socket left intact, not orphaned
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_confirms_sigkill_death_no_spurious_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A process that dies only on SIGKILL is confirmed dead, not falsely raised.

        The owner ignores SIGTERM and exits on SIGKILL, whose delivery is
        asynchronous. _terminate must poll until the process is gone —
        never judge survival from the lingering socket — so reap() clears
        the files without a spurious 'survived' error.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        monkeypatch.setattr("punt_lux.paths._SIGKILL_GRACE", 0.5)
        signalled: list[int] = []

        def fake_kill(pid: int, sig: int) -> None:
            if sig == 0:
                if signal.SIGKILL in signalled:
                    raise ProcessLookupError  # confirmed dead after SIGKILL
                return  # still alive after SIGTERM
            signalled.append(sig)
            if sig == signal.SIGKILL:
                display.stop()

        try:
            with patch("punt_lux.paths.os.kill", side_effect=fake_kill):
                dp.reap(timeout=0.2)  # no raise
            assert signalled == [signal.SIGTERM, signal.SIGKILL]
            assert not path.exists()  # dead socket cleared
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_zombie_owner_confirmed_dead_via_socket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dead-but-unreaped owner that released its socket is confirmed dead.

        The owner exits but lingers as a zombie its real parent has not
        waited, so ``os.kill(pid, 0)`` still succeeds. Its listening fd is
        closed, though, so the authoritative socket reads DEAD. reap() must
        honor the socket and clear files — never SIGKILL a corpse for the
        full grace and then falsely raise 'survived'.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        monkeypatch.setattr("punt_lux.paths._SIGKILL_GRACE", 2.0)
        sent: list[int] = []

        def zombie_kill(_pid: int, sig: int) -> None:
            if sig == 0:
                return  # zombie: PID slot occupied, never ProcessLookupError
            sent.append(sig)
            if sig == signal.SIGTERM:
                display.stop()  # owner exits, releasing the socket (now DEAD)

        def no_child(_pid: int, _flags: int) -> tuple[int, int]:
            raise ChildProcessError  # not our child — cannot reap the zombie

        try:
            with (
                patch("punt_lux.paths.os.kill", side_effect=zombie_kill),
                patch("punt_lux.paths.os.waitpid", side_effect=no_child),
            ):
                dp.reap(timeout=2.0)  # no raise
            assert sent == [signal.SIGTERM]  # socket confirmed death; no SIGKILL
            assert not path.exists()  # dead socket cleared
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_clean_exit_between_probes_is_not_an_error(self) -> None:
        """An owner that exits between the liveness probe and the peer read.

        is_running() is True at the top of reap(), the owner then exits
        cleanly, and _peer_pid() returns None. reap() must re-check
        liveness, find the socket dead, clear files, and NOT raise a
        scary 'owner unresolved' error.
        """
        path = _short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # a real dead socket file for _clear_dead_files to remove
        dp = DisplayPaths(path)

        try:
            with (
                # First probe: alive. Re-check after the None peer: dead.
                patch.object(DisplayPaths, "is_running", side_effect=[True, False]),
                patch.object(DisplayPaths, "_peer_pid", return_value=None),
                patch("punt_lux.paths.os.kill") as kill,
            ):
                dp.reap(timeout=0.2)  # no raise
            kill.assert_not_called()
            assert not path.exists()  # treated as a clean exit, files cleared
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_refuses_non_positive_peer_pid(self) -> None:
        """A zeroed/partial peer credential (pid<=0) refuses — never os.kill(0).

        os.kill(0, SIGTERM) would signal the whole process group — under
        `make restart` that is make, uv, and the shell. A non-positive
        peer PID must resolve to None and reap() must refuse, never signal.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)

        try:
            with (
                # getsockopt yields a zeroed credential → pid 0 → None.
                patch("socket.socket.getsockopt", return_value=b"\x00\x00\x00\x00"),
                patch("punt_lux.paths.os.kill") as kill,
                pytest.raises(RuntimeError, match="refusing to reap"),
            ):
                dp.reap(timeout=0.2)
            kill.assert_not_called()  # never signalled a non-positive PID
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_reap_raises_when_owner_unresolved_no_pid_fallback(self) -> None:
        """A live socket with an unresolvable owner refuses — never a PID fallback.

        When the peer credential cannot be read on a live socket, reap()
        raises rather than falling back to the untrustworthy PID file,
        which could SIGTERM a recycled PID.
        """
        path = _short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))  # tempting, but must be ignored

        try:
            with (
                patch.object(DisplayPaths, "_peer_pid", return_value=None),
                patch("punt_lux.paths.os.kill") as kill,
                pytest.raises(RuntimeError, match="refusing to reap"),
            ):
                dp.reap(timeout=0.3)
            kill.assert_not_called()  # no fallback signal to the PID file value
            assert path.exists()
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)


class TestTerminate:
    """Signal handling distinguishes a vanished process from a live one."""

    def test_process_lookup_error_is_success(self) -> None:
        """A vanished process (ProcessLookupError) terminates cleanly, no raise."""
        dp = DisplayPaths(_short_socket())
        with patch("punt_lux.paths.os.kill", side_effect=ProcessLookupError):
            dp._terminate(4242, timeout=0.3)  # returns without raising

    def test_permission_error_surfaces(self) -> None:
        """EPERM means the process is alive but unsignallable — it must surface."""
        dp = DisplayPaths(_short_socket())
        with (
            patch("punt_lux.paths.os.kill", side_effect=PermissionError),
            pytest.raises(PermissionError),
        ):
            dp._terminate(4242, timeout=0.3)

    def test_non_positive_pid_raises_and_never_signals(self) -> None:
        """The signal path refuses pid<=0 — os.kill(0/-1) hits a process group."""
        dp = DisplayPaths(_short_socket())
        for bad in (0, -1):
            with (
                patch("punt_lux.paths.os.kill") as kill,
                pytest.raises(ValueError, match="non-positive PID"),
            ):
                dp._terminate(bad, timeout=0.2)
            kill.assert_not_called()

    def test_await_exit_reaps_child_zombie(self) -> None:
        """A dead-but-unwaited child is confirmed exited via waitpid, not 'alive'.

        When the reaper is the process's parent, a killed child lingers as a
        zombie and ``os.kill(pid, 0)`` still succeeds. With a *live* socket
        (so the socket check does not short-circuit), _await_exit must reap
        the zombie so death is confirmed rather than mistaken for survival.
        """
        path = _short_socket()
        display = _FakeDisplay(path)  # live socket stays 'alive', isolating waitpid
        dp = DisplayPaths(path)
        proc = subprocess.Popen([sys.executable, "-c", "pass"])  # exits at once
        time.sleep(0.1)  # let it die; deliberately not waited → zombie
        try:
            assert dp._await_exit(proc.pid, timeout=2.0) is True
        finally:
            display.stop()
            shutil.rmtree(path.parent, ignore_errors=True)


class TestIsHubRunning:
    """A non-positive PID never reaches os.kill."""

    def test_non_positive_pid_is_not_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt PID file of '0' or '-1' reads as not running, never signalled."""
        pid_file = tmp_path / "hub.pid"
        monkeypatch.setattr("punt_lux.paths.hub_pid_path", lambda: pid_file)
        for corrupt in ("0", "-1"):
            pid_file.write_text(corrupt)
            with patch("punt_lux.paths.os.kill") as kill:
                assert is_hub_running() is False
            kill.assert_not_called()
