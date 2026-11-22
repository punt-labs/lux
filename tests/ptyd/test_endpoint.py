"""Endpoint permissions, ownership and replacement-safe cleanup."""

from __future__ import annotations

import os
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.credentials import PeerCredentials
from punt_lux.terminal.local_endpoint import LocalEndpoint

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.fixture
def socket_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="lxpty-", dir="/tmp") as directory:
        yield Path(directory)


def test_private_endpoint_and_cleanup(socket_dir: Path) -> None:
    path = socket_dir / "private" / "socket"
    endpoint = LocalEndpoint(path)
    try:
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        endpoint.close()
    endpoint.close()
    assert not path.exists()


def test_long_socket_path_fails_before_creating_directories(socket_dir: Path) -> None:
    path = socket_dir / ("x" * 110) / "socket"
    with pytest.raises(OSError, match="shorter"):
        LocalEndpoint(path)
    assert not path.parent.exists()


def test_insecure_directory_is_not_repaired(socket_dir: Path) -> None:
    directory = socket_dir / "open"
    directory.mkdir(mode=0o755)
    with pytest.raises(PermissionError):
        LocalEndpoint(directory / "socket")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755


def test_existing_file_is_not_removed(socket_dir: Path) -> None:
    directory = socket_dir / "private"
    directory.mkdir(mode=0o700)
    path = directory / "socket"
    path.write_text("keep me")
    with pytest.raises(OSError):
        LocalEndpoint(path)
    assert path.read_text() == "keep me"


def test_replacement_node_is_not_unlinked_on_old_close(socket_dir: Path) -> None:
    path = socket_dir / "private" / "socket"
    endpoint = LocalEndpoint(path)
    path.unlink()
    path.write_text("replacement")
    endpoint.close()
    assert path.read_text() == "replacement"


def test_kernel_peer_uid_matches_this_user() -> None:
    first, second = socket.socketpair()
    try:
        assert PeerCredentials.uid(first) == os.getuid()
        PeerCredentials.require_same_user(first)
    finally:
        first.close()
        second.close()


def test_other_user_is_rejected(monkeypatch: MonkeyPatch) -> None:
    def uid(_peer: socket.socket) -> int:
        return os.getuid() + 1

    monkeypatch.setattr(PeerCredentials, "uid", uid)
    first, second = socket.socketpair()
    try:
        with pytest.raises(PermissionError):
            PeerCredentials.require_same_user(first)
    finally:
        first.close()
        second.close()
