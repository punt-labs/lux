"""Unit tests for punt_lux.display.nonblocking -- Nonblocking.set."""

from __future__ import annotations

import socket

from punt_lux.display.nonblocking import Nonblocking


def test_set_puts_a_blocking_socket_into_non_blocking_mode() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert sock.getblocking() is True  # the stdlib default
        Nonblocking.set(sock)
        assert sock.getblocking() is False
    finally:
        sock.close()


def test_set_is_idempotent_on_an_already_non_blocking_socket() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        Nonblocking.set(sock)
        Nonblocking.set(sock)
        assert sock.getblocking() is False
    finally:
        sock.close()
