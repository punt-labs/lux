"""Lifetime claims protect bind windows and reclaim only owned stale sockets."""

from __future__ import annotations

import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from punt_lux.terminal.daemon_claim import DaemonBusyError, DaemonClaim
from punt_lux.terminal.local_endpoint import LocalEndpoint


@pytest.fixture
def endpoint() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="lxclaim-", dir="/tmp") as directory:
        yield Path(directory) / "p.sock"


def test_claim_blocks_contender_before_listener_exists(endpoint: Path) -> None:
    first = DaemonClaim(endpoint)
    try:
        with pytest.raises(DaemonBusyError):
            DaemonClaim(endpoint)
        assert not endpoint.exists()
    finally:
        first.close()
    second = DaemonClaim(endpoint)
    second.close()
    assert Path(str(endpoint) + ".lock").exists()  # stable inode is intentional


def test_owned_stale_socket_is_removed_under_claim(endpoint: Path) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(endpoint))
    sock.close()
    assert endpoint.exists()
    claim = DaemonClaim(endpoint)
    try:
        assert not endpoint.exists()
    finally:
        claim.close()


def test_live_unguarded_listener_is_never_removed(endpoint: Path) -> None:
    listener = LocalEndpoint(endpoint)
    try:
        with pytest.raises(DaemonBusyError):
            DaemonClaim(endpoint)
        assert endpoint.exists()
    finally:
        listener.close()


def test_non_socket_node_is_preserved(endpoint: Path) -> None:
    endpoint.write_text("keep me")
    with pytest.raises(PermissionError):
        DaemonClaim(endpoint)
    assert endpoint.read_text() == "keep me"
