"""LocalHost -- the name of the machine this process runs on, as a value."""

from __future__ import annotations

import socket
from functools import cache
from typing import final

__all__ = ["LocalHost"]

# What a machine that reports no name is called, so a declared host is never blank.
_UNNAMED = "localhost"


@final
class LocalHost:
    """The machine a client declares as the host it runs on."""

    __slots__ = ()

    @staticmethod
    @cache
    def name() -> str:
        """Return this machine's name, read once.

        A machine's name does not change under a running client, and every
        identity the client builds must declare the same host.
        """
        return LocalHost.named(socket.gethostname())

    @staticmethod
    def named(reported: str) -> str:
        """Return ``reported`` stripped, or ``localhost`` when it is blank."""
        return reported.strip() or _UNNAMED
