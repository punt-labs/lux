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
import errno
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
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest

from punt_lux.paths import DisplayPaths, SocketLiveness
from punt_lux.protocol import HEADER_FORMAT, ReadyMessage, encode_frame, send_message
from punt_lux.socket_server import SocketServer

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


@contextlib.contextmanager
def _silent_holding_server(path: Path) -> Generator[None]:
    """Run a server that accepts connections and holds them open forever.

    Unlike ``_FakeDisplay`` — which closes each accepted connection, giving a
    fast EOF — this never sends and never closes, so a probe's READY-upgrade
    recv actually blocks until ``_HANDSHAKE_TIMEOUT`` elapses. That is the path
    a live-but-slow owner takes. Yields once the listener is bound, so callers
    synchronize on the deterministic ``listening`` event instead of sleeping.
    """
    stop = threading.Event()
    listening = threading.Event()

    def serve() -> None:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(path))
        srv.listen(5)
        srv.settimeout(0.1)
        listening.set()
        held: list[socket.socket] = []
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            held.append(conn)  # hold open: accept but never send or close
        for conn in held:
            conn.close()
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    assert listening.wait(timeout=2)  # server has bound and is listening
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=2)


@pytest.fixture
def short_socket() -> Iterator[Callable[[], Path]]:
    """Yield a factory for short AF_UNIX socket paths (macOS 104-char limit).

    Each call returns a fresh socket path under its own temp dir; every
    temp dir the factory hands out is removed in teardown, so tests need
    no manual cleanup.
    """
    tmpdirs: list[Path] = []

    def make() -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="lux-"))
        tmpdirs.append(tmpdir)
        return tmpdir / "d.sock"

    yield make
    for tmpdir in tmpdirs:
        shutil.rmtree(tmpdir, ignore_errors=True)


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

    def test_no_socket_file(self, short_socket: Callable[[], Path]) -> None:
        dp = DisplayPaths(short_socket())
        assert not dp.is_running()

    def test_live_server_answers(self, short_socket: Callable[[], Path]) -> None:
        path = short_socket()
        display = _FakeDisplay(path)
        try:
            assert DisplayPaths(path).is_running()
        finally:
            display.stop()

    def test_stale_socket_no_listener(self, short_socket: Callable[[], Path]) -> None:
        """A socket file with no listener is dead (connection refused)."""
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # leaves the file, but nothing is listening
        assert not DisplayPaths(path).is_running()

    def test_recycled_pid_is_not_alive(self, short_socket: Callable[[], Path]) -> None:
        """A PID file naming a live unrelated process must not read as alive.

        The PID file records this test process (very much alive), but no
        server listens on the socket. Trusting the PID would be a false
        positive; the socket probe correctly reports dead.
        """
        path = short_socket()
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        assert not dp.is_running()

    def test_bound_socket_without_handshake_is_alive(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A process that accepts a connection owns the socket, handshake or not.

        A live-but-slow display (mid-render, breakpoint, slow GPU) accepts
        the connection but may miss the handshake window. Acceptance alone
        proves a live owner: it must read as running so it is never spawned
        over nor unlinked.
        """
        path = short_socket()
        display = _FakeDisplay(path, answer=False)
        try:
            assert DisplayPaths(path).is_running()
        finally:
            display.stop()

    def test_probe_distinguishes_accepting_from_ready(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """_probe reports READY on handshake, ACCEPTING on a silent listener."""
        ready_path = short_socket()
        ready = _FakeDisplay(ready_path)
        silent_path = short_socket()
        silent = _FakeDisplay(silent_path, answer=False)
        try:
            assert DisplayPaths(ready_path)._probe() is SocketLiveness.READY
            assert DisplayPaths(silent_path)._probe() is SocketLiveness.ACCEPTING
        finally:
            ready.stop()
            silent.stop()

    def test_probe_silent_owner_is_accepting(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live owner that holds the connection open reads ACCEPTING.

        Connect-success proves the owner is not DEAD; whether the probe then
        returns ACCEPTING or READY depends on the READY-upgrade recv. Here the
        server accepts and HOLDS the connection (never sends, never closes), so
        that recv times out after _HANDSHAKE_TIMEOUT and the fall-through yields
        ACCEPTING. (A _FakeDisplay closes the connection, giving a fast EOF that
        would not exercise this blocking-recv path.)
        """
        path = short_socket()
        with _silent_holding_server(path):
            assert DisplayPaths(path)._probe() is SocketLiveness.ACCEPTING

    @pytest.mark.slow
    def test_probe_silent_owner_resolves_before_connect_timeout(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A silent-but-live owner resolves on the handshake window, not connect.

        Times _probe against a server that accepts and holds the connection
        open. The 0.5s bound sits strictly between the two probe constants: the
        READY-upgrade recv waits at most _HANDSHAKE_TIMEOUT (~0.2s), while the
        connect budget is the full _PROBE_TIMEOUT (~1.0s). A correct probe
        returns after the handshake window (~0.2s), so 0.5s passes; a regression
        that blocks the whole connect timeout on a silent owner (~1.0s) fails.

        Marked slow because an absolute wall-clock bound tracks machine load,
        not code, and must stay out of the default serial gate.
        """
        path = short_socket()
        with _silent_holding_server(path):
            start = time.perf_counter()
            result = DisplayPaths(path)._probe()
            elapsed = time.perf_counter() - start
        assert result is SocketLiveness.ACCEPTING
        assert elapsed < 0.5

    def test_probe_refused_socket_is_dead(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """_probe reports DEAD when the file exists but nothing listens."""
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()
        assert DisplayPaths(path)._probe() is SocketLiveness.DEAD

    def test_probe_malformed_frame_is_accepting(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live owner answering with a malformed first frame reads ACCEPTING.

        A present-but-undecodable frame proves a live owner answered, so it
        must not crash the probe nor read as dead.
        """
        path = short_socket()
        display = _FakeDisplay(path, reply="garbage")
        try:
            assert DisplayPaths(path)._probe() is SocketLiveness.ACCEPTING
        finally:
            display.stop()

    def test_probe_nonobject_payload_is_accepting(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live owner replying with a JSON non-object does not crash the probe.

        A valid frame whose JSON payload is ``42`` (not an object) makes the
        decoder's ``d.get("type")`` raise AttributeError. Connect already
        proved a live owner, so the probe must read ACCEPTING — not let the
        exception escape and crash is_running().
        """
        path = short_socket()
        display = _FakeDisplay(path, reply="nonobject")
        try:
            dp = DisplayPaths(path)
            assert dp._probe() is SocketLiveness.ACCEPTING
            assert dp.is_running() is True  # never raised
        finally:
            display.stop()

    def test_probe_connect_timeout_is_accepting_and_preserves_socket(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A connect that times out is a live-but-overloaded owner → ACCEPTING.

        settimeout applies to connect() too; a slow owner whose connect
        can't complete in the probe window must read ACCEPTING (presence
        wins), and cleanup_stale must never unlink its socket.
        """
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # socket file exists; connect is what we force to time out
        dp = DisplayPaths(path)
        with patch("socket.socket.connect", side_effect=TimeoutError):
            assert dp._probe() is SocketLiveness.ACCEPTING
            dp.cleanup_stale()  # must not unlink a possibly-live socket
        assert path.exists()

    def test_probe_connect_resource_error_is_accepting_and_preserves_socket(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A non-refused connect error (fd exhaustion) reads ACCEPTING, not dead.

        Reaper-side EMFILE/ENFILE makes connect raise a generic OSError. That
        is ambiguous, not proof of a dead owner, so _probe must read ACCEPTING
        and cleanup_stale must never unlink a possibly-live socket.
        """
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # socket file exists; connect is what we force to fail
        dp = DisplayPaths(path)
        emfile = OSError(errno.EMFILE, "too many open files")
        with patch("socket.socket.connect", side_effect=emfile):
            assert dp._probe() is SocketLiveness.ACCEPTING
            dp.cleanup_stale()
        assert path.exists()  # ambiguous error never unlinks the socket

    def test_probe_recursion_error_reply_is_accepting(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A pathological reply that raises RecursionError does not crash the probe.

        Deeply-nested JSON overflows the decoder's recursion limit. The connect
        already proved a live owner, so the probe must read ACCEPTING rather
        than let RecursionError escape and crash is_running().
        """
        path = short_socket()
        display = _FakeDisplay(path)  # live socket; connect succeeds
        dp = DisplayPaths(path)
        try:
            with patch("punt_lux.paths.recv_message", side_effect=RecursionError):
                assert dp._probe() is SocketLiveness.ACCEPTING
                assert dp.is_running() is True  # never raised
        finally:
            display.stop()

    def test_bound_not_listening_socket_probes_dead(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A socket bound but not yet listening refuses connect, so it reads DEAD.

        This is the bind window: between ``bind`` and ``listen`` the path exists
        as a socket file, but a probe's ``connect`` gets ECONNREFUSED. That the
        window reads DEAD is the entire justification for the bind lock — without
        it a concurrent cleanup would unlink this fresh bind. Exercised with a
        real bound socket, not a monkeypatched probe.
        """
        path = short_socket()
        bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound.bind(str(path))  # bound, fd held open, listen() deliberately skipped
        try:
            dp = DisplayPaths(path)
            assert path.is_socket()  # the file is present in the window
            assert dp._probe() is SocketLiveness.DEAD
            assert dp.is_running() is False
        finally:
            bound.close()


class TestCleanupStale:
    def test_removes_dead_socket(self, short_socket: Callable[[], Path]) -> None:
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()
        dp = DisplayPaths(path)
        dp.pid_path.write_text("999999999")
        dp.cleanup_stale()
        assert not path.exists()
        assert not dp.pid_path.exists()

    def test_preserves_live_socket(self, short_socket: Callable[[], Path]) -> None:
        """A live display's socket and PID file are never removed."""
        path = short_socket()
        display = _FakeDisplay(path)
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        try:
            dp.cleanup_stale()
            assert path.exists()
            assert dp.pid_path.exists()
        finally:
            display.stop()

    def test_removes_non_socket_file(self, short_socket: Callable[[], Path]) -> None:
        """A regular file at the socket path is dead and fully cleared.

        Classification is by ``is_socket()`` (stat/S_ISSOCK), not by the
        errno ``connect()`` raises — which differs by platform (macOS
        ENOTSOCK vs Linux ECONNREFUSED). A non-socket file has no live
        owner, so cleanup_stale removes both it and the PID file so a
        fresh display can bind. The assertion is platform-agnostic.
        """
        path = short_socket()
        path.write_text("not a socket")
        dp = DisplayPaths(path)
        dp.pid_path.write_text("999999999")
        assert not dp.is_running()  # non-socket => DEAD on both platforms
        dp.cleanup_stale()
        assert not path.exists()  # stale file cleared for a fresh bind
        assert not dp.pid_path.exists()

    def test_preserves_accepting_but_silent_socket(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live-but-slow display's socket is never unlinked on a missing handshake.

        The socket accepts the connection but sends no ReadyMessage within
        the probe window. Unlinking it would orphan the live owner and let
        the next spawn stack a second window — the exact bug the accepting
        invariant closes.
        """
        path = short_socket()
        display = _FakeDisplay(path, answer=False)
        dp = DisplayPaths(path)
        try:
            dp.cleanup_stale()
            assert path.exists()  # accepting socket preserved, owner not orphaned
        finally:
            display.stop()


class TestWriteRemovePid:
    def test_roundtrip(self, tmp_path: Path) -> None:
        dp = DisplayPaths(tmp_path / "display.sock")
        dp.write_pid()
        assert dp.pid_path.exists()
        assert int(dp.pid_path.read_text().strip()) == os.getpid()

        dp.remove_pid()
        assert not dp.pid_path.exists()


class TestEnsure:
    def test_already_running_reuses(self, short_socket: Callable[[], Path]) -> None:
        """A live display is reused — ensure() does not spawn."""
        path = short_socket()
        display = _FakeDisplay(path)
        try:
            with patch("punt_lux.paths.subprocess.Popen") as popen:
                result = DisplayPaths(path).ensure()
            assert result == path
            popen.assert_not_called()
        finally:
            display.stop()

    def test_idempotent_second_ensure_does_not_spawn(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """Once a display answers, a second ensure() reuses it with no spawn."""
        path = short_socket()
        display = _FakeDisplay(path)
        try:
            dp = DisplayPaths(path)
            with patch("punt_lux.paths.subprocess.Popen") as popen:
                dp.ensure()
                dp.ensure()
            popen.assert_not_called()
        finally:
            display.stop()

    def test_stale_pid_file_preserves_live_socket(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """The core regression: a live display with a missing/stale PID file.

        Remove the PID file while the display is alive. ensure() must NOT
        unlink the live socket and must NOT spawn a second process — it
        reuses the live server confirmed by the handshake.
        """
        path = short_socket()
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

    def test_does_not_spawn_over_accepting_socket(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live-but-slow display is reused, never duplicated.

        The socket accepts the connection but the handshake is absent, so a
        handshake-only liveness check would spawn a second window. ensure()
        reuses the accepting owner and never calls Popen.
        """
        path = short_socket()
        display = _FakeDisplay(path, answer=False)
        try:
            with patch("punt_lux.paths.subprocess.Popen") as popen:
                result = DisplayPaths(path).ensure()
            assert result == path
            popen.assert_not_called()  # no duplicate window spawned
        finally:
            display.stop()

    def test_spawns_when_dead(self, short_socket: Callable[[], Path]) -> None:
        path = short_socket()
        dp = DisplayPaths(path)
        displays: list[_FakeDisplay] = []

        def fake_popen(*_args: object, **_kwargs: object) -> object:
            displays.append(_FakeDisplay(path))

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
            for display in displays:
                display.stop()

    def test_timeout_raises(self, short_socket: Callable[[], Path]) -> None:
        path = short_socket()
        dp = DisplayPaths(path)

        class FakeProc:
            pid = 1

        with (
            patch("punt_lux.paths.subprocess.Popen", return_value=FakeProc()),
            pytest.raises(RuntimeError, match="failed to start"),
        ):
            dp.ensure(timeout=0.3)

    def test_concurrent_ensure_spawns_once(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """Two near-simultaneous ensure() calls spawn exactly one display.

        The spawn lock serializes the callers; the first spawns a display,
        the second observes it on the re-check and reuses it.
        """
        path = short_socket()
        spawn_count = 0
        lock = threading.Lock()
        displays: list[_FakeDisplay] = []

        def fake_popen(*_args: object, **_kwargs: object) -> object:
            nonlocal spawn_count
            with lock:
                spawn_count += 1
                displays.append(_FakeDisplay(path))

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
            for display in displays:
                display.stop()

    def test_make_restart_ensure_reuses_display_spawned_in_reap_gap(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """`make restart`'s reap()+ensure() reuses a display raced in mid-gap.

        Models the Makefile sequence (reap then ensure) with the beads hook's
        ensure() sneaking a spawn into the gap after reap releases the lock.
        make-restart's ensure() checks is_running() under the lock and REUSES
        it — exactly one display, never the two the old bare `lux display &`
        produced. A dead socket means reap just clears (no signal), so no
        os.kill is patched.
        """
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # dead socket → reap clears, no owner to signal
        spawn_count = 0
        displays: list[_FakeDisplay] = []
        reap_done = threading.Event()
        hook_spawned = threading.Event()

        def fake_popen(*_a: object, **_k: object) -> object:
            nonlocal spawn_count
            spawn_count += 1
            displays.append(_FakeDisplay(path))

            class FakeProc:
                pid = os.getpid()

            return FakeProc()

        restart_dp = DisplayPaths(path)
        hook_dp = DisplayPaths(path)

        def make_restart() -> None:
            restart_dp.reap(timeout=2.0)  # dead → clears the socket
            reap_done.set()  # now in the reap->ensure gap
            assert hook_spawned.wait(timeout=5), "hook never spawned"
            restart_dp.ensure(timeout=3.0)  # must reuse, not spawn a second

        def beads_hook() -> None:
            assert reap_done.wait(timeout=5), "reap never released"
            hook_dp.ensure(timeout=3.0)  # spawns the single display
            hook_spawned.set()

        try:
            with patch("punt_lux.paths.subprocess.Popen", side_effect=fake_popen):
                threads = [
                    threading.Thread(target=make_restart),
                    threading.Thread(target=beads_hook),
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=10)
            assert spawn_count == 1  # exactly one display despite the race
        finally:
            for display in displays:
                display.stop()


class TestPeerPid:
    """The socket's OS peer credential resolves the true owner PID."""

    def test_live_socket_returns_owner_pid(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live listener's peer credential names its owning process."""
        path = short_socket()
        display = _FakeDisplay(path)
        try:
            # The FakeDisplay binds in this process, so it owns the socket.
            assert DisplayPaths(path)._peer_pid() == os.getpid()
        finally:
            display.stop()

    def test_dead_socket_returns_none(self, short_socket: Callable[[], Path]) -> None:
        """A stale socket with no listener yields no peer (connection refused)."""
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # file remains, nothing listens
        assert DisplayPaths(path)._peer_pid() is None

    def test_unsupported_platform_returns_none(
        self, short_socket: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A platform without a peer-credential option yields None."""
        path = short_socket()
        display = _FakeDisplay(path)
        monkeypatch.setattr("punt_lux.paths.sys.platform", "sunos5")
        try:
            assert DisplayPaths(path)._peer_pid() is None
        finally:
            display.stop()

    def test_non_positive_credential_returns_none(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A zeroed/partial credential (pid 0) resolves to None, never a target.

        os.kill(0, ...) signals the whole process group; a non-positive
        peer PID must never leave _peer_pid as a signallable value.
        """
        path = short_socket()
        display = _FakeDisplay(path)
        try:
            with patch("socket.socket.getsockopt", return_value=b"\x00\x00\x00\x00"):
                assert DisplayPaths(path)._peer_pid() is None
        finally:
            display.stop()


class TestReap:
    def test_reap_dead_clears_files_without_kill(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A stale/recycled PID is never signalled when the socket is dead."""
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        with patch("punt_lux.paths.os.kill") as kill:
            dp.reap()
        kill.assert_not_called()  # recycled-PID friendly-fire avoided
        assert not path.exists()
        assert not dp.pid_path.exists()

    def test_reap_live_terminates_owner(self, short_socket: Callable[[], Path]) -> None:
        """A live display is terminated via its socket owner, then cleaned.

        The ``_FakeDisplay`` binds in this process, so the socket's peer
        credential and the recorded PID file agree on this test's PID.
        """
        path = short_socket()
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

    def test_reap_live_without_pid_uses_socket_owner(
        self, short_socket: Callable[[], Path]
    ) -> None:
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
        path = short_socket()
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

    def test_reap_live_prefers_socket_owner_over_stale_pid(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A divergent PID file does not misdirect the kill.

        With a live display and a PID file naming a different, unrelated
        PID, reap() must signal the socket's true owner (this process),
        never the stale file value — the socket wins on identity.
        """
        path = short_socket()
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

    def test_reap_terminates_accepting_but_silent_owner(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live-but-slow display is reaped via its owner, not unlink-only.

        The socket accepts but never handshakes. reap() must resolve the
        owner via the peer credential and terminate it — never silently
        unlink the socket while leaving the process running.
        """
        path = short_socket()
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

    def test_reap_raises_when_owner_survives_termination(
        self, short_socket: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reap() raises so the caller (make restart) does not spawn over a survivor.

        The owner ignores SIGTERM and SIGKILL — os.kill(pid, 0) keeps
        reporting it alive. reap() must raise rather than clear files and
        let a second display spawn atop the still-held socket.
        """
        path = short_socket()
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

    def test_reap_confirms_sigkill_death_no_spurious_raise(
        self, short_socket: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A process that dies only on SIGKILL is confirmed dead, not falsely raised.

        The owner ignores SIGTERM and exits on SIGKILL, whose delivery is
        asynchronous. _terminate must poll until the process is gone —
        never judge survival from the lingering socket — so reap() clears
        the files without a spurious 'survived' error.
        """
        path = short_socket()
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

    def test_reap_zombie_owner_confirmed_dead_via_socket(
        self, short_socket: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dead-but-unreaped owner that released its socket is confirmed dead.

        The owner exits but lingers as a zombie its real parent has not
        waited, so ``os.kill(pid, 0)`` still succeeds. Its listening fd is
        closed, though, so the authoritative socket reads DEAD. reap() must
        honor the socket and clear files — never SIGKILL a corpse for the
        full grace and then falsely raise 'survived'.
        """
        path = short_socket()
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

    def test_reap_clean_exit_between_probes_is_not_an_error(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """An owner that exits between the liveness probe and the peer read.

        is_running() is True at the top of reap(), the owner then exits
        cleanly, and _peer_pid() returns None. reap() must re-check
        liveness, find the socket dead, clear files, and NOT raise a
        scary 'owner unresolved' error.
        """
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # a real dead socket file for _clear_dead_files to remove
        dp = DisplayPaths(path)

        with (
            # Probe 1: alive. Probe 2 (after None peer): dead. Probe 3
            # (_clear_dead_files re-probe before unlink): dead.
            patch.object(DisplayPaths, "is_running", side_effect=[True, False, False]),
            patch.object(DisplayPaths, "_peer_pid", return_value=None),
            patch("punt_lux.paths.os.kill") as kill,
        ):
            dp.reap(timeout=0.2)  # no raise
        kill.assert_not_called()
        assert not path.exists()  # treated as a clean exit, files cleared

    def test_reap_refuses_non_positive_peer_pid(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A zeroed/partial peer credential (pid<=0) refuses — never os.kill(0).

        os.kill(0, SIGTERM) would signal the whole process group — under
        `make restart` that is make, uv, and the shell. A non-positive
        peer PID must resolve to None and reap() must refuse, never signal.
        """
        path = short_socket()
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

    def test_reap_raises_when_owner_unresolved_no_pid_fallback(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A live socket with an unresolvable owner refuses — never a PID fallback.

        When the peer credential cannot be read on a live socket, reap()
        raises rather than falling back to the untrustworthy PID file,
        which could SIGTERM a recycled PID.
        """
        path = short_socket()
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

    def test_reap_holds_lock_against_concurrent_ensure(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """reap holds the spawn lock so a concurrent ensure() cannot spawn mid-reap.

        While reap is inside its locked cleanup, a second thread's ensure()
        blocks on the same flock and must not spawn a display until reap
        releases — closing the TOCTOU where ensure would bind a socket that
        reap's cleanup then unlinks.
        """
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # dead socket → reap takes the clear-files branch
        reaper = DisplayPaths(path)
        spawner = DisplayPaths(path)
        in_cleanup = threading.Event()
        release = threading.Event()
        spawned: list[_FakeDisplay] = []
        orig_clear = DisplayPaths._clear_dead_files

        def blocking_clear(self: DisplayPaths) -> None:
            in_cleanup.set()  # reap now holds the lock
            assert release.wait(timeout=5), "release never signalled"
            orig_clear(self)

        def fake_popen(*_a: object, **_k: object) -> object:
            spawned.append(_FakeDisplay(path))

            class FakeProc:
                pid = os.getpid()

            return FakeProc()

        try:
            with patch.object(DisplayPaths, "_clear_dead_files", blocking_clear):
                t_reap = threading.Thread(target=reaper.reap)
                t_reap.start()
                assert in_cleanup.wait(timeout=5), "reap never entered cleanup"
                with patch(
                    "punt_lux.paths.subprocess.Popen", side_effect=fake_popen
                ) as popen:
                    t_ensure = threading.Thread(
                        target=lambda: spawner.ensure(timeout=3.0)
                    )
                    t_ensure.start()
                    time.sleep(0.3)  # ensure would spawn by now if not blocked
                    assert popen.call_count == 0, "ensure spawned while reap held lock"
                    release.set()  # let reap finish and release the lock
                    t_ensure.join(timeout=5)
                    assert popen.call_count > 0  # ensure proceeded after reap released
                t_reap.join(timeout=5)
        finally:
            for display in spawned:
                display.stop()

    def test_clear_dead_files_skips_live_socket(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """_clear_dead_files re-probes and never unlinks a socket a live owner bound.

        Defense in depth for the reap-vs-spawn race: if a new owner binds the
        socket between confirm-dead and cleanup, the re-probe reads it live and
        skips the unlink, leaving the new window's socket and PID file intact.
        """
        path = short_socket()
        display = _FakeDisplay(path)  # a live owner holds the socket
        dp = DisplayPaths(path)
        dp.pid_path.write_text(str(os.getpid()))
        try:
            dp._clear_dead_files()  # re-probe sees a live owner → no unlink
            assert path.exists()  # live socket preserved
            assert dp.pid_path.exists()  # live owner's PID file preserved
        finally:
            display.stop()

    def test_clear_dead_files_removes_broken_symlink(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A broken symlink at the socket path is removed so a fresh bind() succeeds.

        is_file() follows the dangling link (→ False) and is_socket() is False,
        so the old file/socket-only check would leave the symlink blocking
        bind(). os.path.lexists() sees the link itself; unlink removes the link,
        not its (absent) target.
        """
        path = short_socket()
        path.symlink_to(path.parent / "does-not-exist.target")  # broken symlink
        dp = DisplayPaths(path)
        dp.pid_path.write_text("999999999")
        assert path.is_symlink() and not path.exists()  # present but dangling
        dp._clear_dead_files()
        assert not os.path.lexists(path)  # the symlink itself is gone
        assert not dp.pid_path.exists()  # pid file cleared too
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))  # a fresh bind now succeeds — no leftover blocking it
        s.close()

    def test_clear_dead_files_preserves_symlink_to_live_socket(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A symlink to a LIVE socket is preserved by the is_running guard."""
        real = short_socket()
        display = _FakeDisplay(real)
        link = short_socket()  # a separate path for the symlink
        link.symlink_to(real)  # link → the live socket
        try:
            dp = DisplayPaths(link)
            assert dp.is_running()  # is_socket() follows the link to the live socket
            dp._clear_dead_files()
            assert link.is_symlink()  # live owner → symlink left intact
            assert real.exists()  # the real socket untouched
        finally:
            display.stop()

    def test_reap_cleanup_holds_bind_lock_against_binder(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """reap's dead-file cleanup takes the bind lock, so a binder serializes it.

        ``reap`` clears a dead socket via ``_clear_dead_files_locked``, which
        acquires the bind lock. A concurrent binder holding that lock must block
        reap's cleanup: the stale socket is not unlinked while the binder holds
        the lock, and reap completes the unlink only once the binder releases.
        This is the reap-side counterpart of the setup arbitration serialization.
        """
        path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.close()  # dead socket file → reap takes the clear-files branch
        assert path.exists()
        binder = DisplayPaths(path)
        reaper = DisplayPaths(path)
        result: list[str] = []
        reaping = threading.Event()
        worker: threading.Thread | None = None

        def do_reap() -> None:
            reaping.set()
            reaper.reap(timeout=2.0)
            result.append("done")

        try:
            with binder.bind_lock():
                worker = threading.Thread(target=do_reap)
                worker.start()
                assert reaping.wait(timeout=2)
                worker.join(timeout=0.5)
                assert worker.is_alive()  # blocked on the bind lock in cleanup
                assert path.exists()  # dead socket not unlinked while binder holds lock
            worker.join(timeout=5)
            assert not worker.is_alive(), "reap did not finish after the lock released"
            assert result == ["done"]
            assert not path.exists()  # unlinked only after the binder released
        finally:
            if worker is not None:
                worker.join(timeout=5)


class TestLockOrdering:
    """The spawn and bind locks obey a fixed order (spawn→bind), so no cycle forms."""

    def test_spawn_and_bind_locks_coexist_without_deadlock(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """Two agents taking spawn-then-bind never deadlock (Invariant 4).

        ``ensure`` holds the spawn lock while the display it spawns takes the
        bind lock; the design claim is that the fixed order — spawn outer, bind
        inner, never both by one agent in the reverse order — makes a cyclic
        wait impossible. Two threads acquire the real flocks in that order under
        a barrier; a deadlock would hang the joins. Both completing proves the
        ordering is safe.
        """
        path = short_socket()
        start = threading.Barrier(2)
        completed: list[int] = []
        lock = threading.Lock()

        def acquire_in_order(tag: int) -> None:
            start.wait()  # release both threads together to force contention
            dp = DisplayPaths(path)
            with dp._spawn_lock(), dp.bind_lock():
                time.sleep(0.05)  # hold both, widening the contention window
            with lock:
                completed.append(tag)

        threads = [
            threading.Thread(target=acquire_in_order, args=(i,)) for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert all(not t.is_alive() for t in threads)  # neither hung on a cycle
        assert sorted(completed) == [0, 1]  # both acquired and released both locks

    def test_lock_acquisition_order_invariant(
        self, short_socket: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real setup/ensure/reap paths take locks in spawn→bind order.

        Deadlock-freedom rests on a fixed acquisition order: the spawn lock is
        always outer, the bind lock always inner, and no path takes them in the
        reverse order. The coexist test proves only that two agents using the
        SAME order do not hang — it cannot catch an order INVERSION introduced
        later inside a real method. This spies on ``_file_lock`` and asserts the
        exact order the real methods record, so inverting the order — or having
        ``setup`` start taking the spawn lock — fails deterministically.
        """
        events: list[tuple[str, str]] = []
        original_file_lock = DisplayPaths._file_lock

        @contextlib.contextmanager
        def spy_file_lock(dp: DisplayPaths, lock_path: Path) -> Generator[None]:
            which = "bind" if lock_path == dp._bind_lock_path else "spawn"
            with original_file_lock(dp, lock_path):
                events.append(("acquire", which))
                try:
                    yield
                finally:
                    events.append(("release", which))

        monkeypatch.setattr(DisplayPaths, "_file_lock", spy_file_lock)

        def noop_message(_sock: socket.socket, _msg: object) -> None:
            """Discard inbound messages — the server never serves here."""

        def noop_disconnect(_fd: int) -> None:
            """Ignore client disconnects."""

        def noop_error(_sev: str, _msg: str, _ctx: str) -> None:
            """Ignore error reports."""

        # setup(): only ever the bind lock — never the spawn lock.
        events.clear()
        server = SocketServer(
            on_message=noop_message,
            on_client_disconnected=noop_disconnect,
            on_error=noop_error,
        )
        try:
            assert server.setup(short_socket()) is True
        finally:
            server.shutdown()
        assert events == [("acquire", "bind"), ("release", "bind")]
        assert ("acquire", "spawn") not in events  # setup must not take the spawn lock

        # ensure(): spawn lock outer, bind lock inner and RELEASED before _spawn,
        # so the cross-process bind never nests inside a held spawn lock.
        events.clear()
        ensure_path = short_socket()

        def record_spawn(_dp: DisplayPaths) -> None:
            events.append(("spawn_process", ""))

        def skip_await(_dp: DisplayPaths, _timeout: float) -> Path:
            return ensure_path

        with (
            patch.object(DisplayPaths, "_spawn", record_spawn),
            patch.object(DisplayPaths, "_await_ready", skip_await),
        ):
            assert DisplayPaths(ensure_path).ensure(timeout=1.0) == ensure_path
        assert events == [
            ("acquire", "spawn"),
            ("acquire", "bind"),
            ("release", "bind"),
            ("spawn_process", ""),
            ("release", "spawn"),
        ]

        # reap(): dead path → spawn lock outer, bind lock inner, no kill.
        events.clear()
        reap_path = short_socket()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(reap_path))
        s.close()  # stale socket → reap clears under the locks, no owner to signal
        DisplayPaths(reap_path).reap(timeout=1.0)
        assert events == [
            ("acquire", "spawn"),
            ("acquire", "bind"),
            ("release", "bind"),
            ("release", "spawn"),
        ]


class TestTerminate:
    """Signal handling distinguishes a vanished process from a live one."""

    def test_process_lookup_error_is_success(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A vanished process (ProcessLookupError) terminates cleanly, no raise."""
        dp = DisplayPaths(short_socket())
        with patch("punt_lux.paths.os.kill", side_effect=ProcessLookupError):
            dp._terminate(4242, timeout=0.3)  # returns without raising

    def test_permission_error_surfaces(self, short_socket: Callable[[], Path]) -> None:
        """EPERM means the process is alive but unsignallable — it must surface."""
        dp = DisplayPaths(short_socket())
        with (
            patch("punt_lux.paths.os.kill", side_effect=PermissionError),
            pytest.raises(PermissionError),
        ):
            dp._terminate(4242, timeout=0.3)

    def test_non_positive_pid_raises_and_never_signals(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """The signal path refuses pid<=0 — os.kill(0/-1) hits a process group."""
        dp = DisplayPaths(short_socket())
        for bad in (0, -1):
            with (
                patch("punt_lux.paths.os.kill") as kill,
                pytest.raises(ValueError, match="non-positive PID"),
            ):
                dp._terminate(bad, timeout=0.2)
            kill.assert_not_called()

    def test_await_exit_reaps_child_zombie(
        self, short_socket: Callable[[], Path]
    ) -> None:
        """A dead-but-unwaited child is confirmed exited via waitpid, not 'alive'.

        When the reaper is the process's parent, a killed child lingers as a
        zombie and ``os.kill(pid, 0)`` still succeeds. With a *live* socket
        (so the socket check does not short-circuit), _await_exit must reap
        the zombie so death is confirmed rather than mistaken for survival.
        """
        path = short_socket()
        display = _FakeDisplay(path)  # live socket stays 'alive', isolating waitpid
        dp = DisplayPaths(path)
        proc = subprocess.Popen([sys.executable, "-c", "pass"])  # exits at once
        time.sleep(0.1)  # let it die; deliberately not waited → zombie
        try:
            assert dp._await_exit(proc.pid, timeout=2.0) is True
        finally:
            if proc.poll() is None:  # _await_exit already reaped it if it ran
                proc.kill()
                proc.wait(timeout=2)
            display.stop()
