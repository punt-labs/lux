"""Peer UID authentication for local Unix sockets; no caller-claimed identity."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import socket
import struct


class PeerCredentials:
    """Use kernel credentials on Linux and getpeereid on BSD/macOS."""

    @classmethod
    def require_same_user(cls, peer: socket.socket) -> None:
        if cls.uid(peer) != os.getuid():
            raise PermissionError("terminal socket peer has another UID")

    @staticmethod
    def uid(peer: socket.socket) -> int:
        option = getattr(socket, "SO_PEERCRED", None)
        if isinstance(option, int):
            raw = peer.getsockopt(socket.SOL_SOCKET, option, 12)
            _pid, uid, _gid = struct.unpack("iII", raw)
            return int(uid)
        libc_path = ctypes.util.find_library("c")
        if not libc_path:
            raise OSError("cannot locate peer credential API")
        libc = ctypes.CDLL(libc_path, use_errno=True)
        getpeereid = libc.getpeereid
        getpeereid.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        getpeereid.restype = ctypes.c_int
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        if getpeereid(peer.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise OSError(ctypes.get_errno(), "getpeereid failed")
        return uid.value
