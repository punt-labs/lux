"""SocketOwner — the kernel's answer to who is behind a Unix socket.

The reap path signals whoever these tests say owns the socket, so both directions
matter equally: a live owner must be resolved even when the first read fails, and
an absent owner must stay absent rather than becoming a signallable value.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Self, final
from unittest.mock import patch

import pytest

from punt_lux.socket_owner import SocketOwner

if TYPE_CHECKING:
    from collections.abc import Generator


@final
class _Listener:
    """A bound, listening socket owned by this process — a stand-in display."""

    _sock: socket.socket
    __slots__ = ("_sock",)

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(path))
        self._sock.listen(5)
        return self

    def close(self) -> None:
        self._sock.close()


@pytest.fixture
def sock_path() -> Generator[Path]:
    """A short socket path — macOS caps AF_UNIX paths at ~104 characters.

    Removed on teardown: ``mkdtemp`` has no owner of its own, so a fixture that
    only creates one leaves a directory per test behind forever.
    """
    directory = tempfile.mkdtemp(prefix="lux-")
    try:
        yield Path(directory) / "d.sock"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_a_live_socket_names_its_owning_process(sock_path: Path) -> None:
    listener = _Listener(sock_path)
    try:
        assert SocketOwner(sock_path).pid() == os.getpid()
    finally:
        listener.close()


def test_a_transient_connect_failure_does_not_lose_the_owner(
    sock_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One refused connect must not turn a live owner into an unresolvable one.

    This is the failure that shows up under load: a live owner whose accept
    backlog is momentarily full refuses or stalls a single connect. A one-shot
    read concludes the owner cannot be resolved, and the caller then declines to
    reap a display that is plainly there. The first attempt is failed
    deterministically here rather than waiting for load to do it.
    """
    listener = _Listener(sock_path)
    real_connect = socket.socket.connect
    attempts = 0

    def flaky_connect(sock: socket.socket, address: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("timed out")
        real_connect(sock, address)  # type: ignore[arg-type]  # the real address object

    try:
        monkeypatch.setattr(socket.socket, "connect", flaky_connect)
        assert SocketOwner(sock_path).pid() == os.getpid()
        assert attempts > 1  # it retried rather than got lucky
    finally:
        listener.close()


def test_a_socket_nobody_owns_resolves_to_none_and_bounds_its_asking(
    sock_path: Path,
) -> None:
    """Retrying must not turn "no owner" into a hang or a wrong answer."""
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(sock_path))
    stale.close()  # the file remains, nothing listens

    start = time.monotonic()
    assert SocketOwner(sock_path).pid() is None
    # Every attempt is refused immediately, so the retries stay well inside any
    # caller's budget rather than accumulating a connect timeout each.
    assert time.monotonic() - start < 5.0


def test_an_unsupported_platform_resolves_to_none(
    sock_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a peer-credential option there is no owner to name."""
    listener = _Listener(sock_path)
    monkeypatch.setattr("punt_lux.socket_owner.sys.platform", "sunos5")
    try:
        assert SocketOwner(sock_path).pid() is None
    finally:
        listener.close()


def test_a_non_positive_credential_is_never_a_target(sock_path: Path) -> None:
    """A zeroed or partial credential resolves to None, never a signallable pid.

    ``os.kill(0, ...)`` signals the caller's whole process group, so a pid of 0
    must not survive this read as something the reap path could aim at.
    """
    listener = _Listener(sock_path)
    try:
        with patch("socket.socket.getsockopt", return_value=b"\x00\x00\x00\x00"):
            assert SocketOwner(sock_path).pid() is None
    finally:
        listener.close()
