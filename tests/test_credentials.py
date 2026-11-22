"""Local socket authentication uses kernel identity and fails closed."""

from __future__ import annotations

import ctypes.util
import os
import socket

import pytest

from punt_lux.credentials import PeerCredentials


def test_kernel_peer_uid_matches_this_user() -> None:
    first, second = socket.socketpair()
    try:
        assert PeerCredentials.uid(first) == os.getuid()
        PeerCredentials.require_same_user(first)
    finally:
        first.close()
        second.close()


def test_other_user_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def uid(_peer: socket.socket) -> int:
        return os.getuid() + 1

    monkeypatch.setattr(PeerCredentials, "uid", uid)
    first, second = socket.socketpair()
    with first, second, pytest.raises(PermissionError, match="another UID"):
        PeerCredentials.require_same_user(first)


def test_closed_socket_cannot_supply_credentials() -> None:
    with socket.socket() as peer:
        peer.close()
        with pytest.raises(OSError):
            PeerCredentials.uid(peer)


def test_missing_credential_api_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_library(_name: str) -> str:
        return ""

    monkeypatch.delattr(socket, "SO_PEERCRED", raising=False)
    monkeypatch.setattr(ctypes.util, "find_library", missing_library)
    with (
        socket.socket() as peer,
        pytest.raises(OSError, match="cannot locate peer credential API"),
    ):
        PeerCredentials.require_same_user(peer)
