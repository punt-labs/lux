"""LocalHost -- the name of the machine this process runs on, as a value."""

from __future__ import annotations

import ipaddress
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
        """Return ``reported`` stripped, or ``localhost`` when blank or unprintable.

        A name with a control character could not pass the identity model's
        host check, so it would make every identity this client builds invalid.
        """
        name = reported.strip()
        return name if name and name.isprintable() else _UNNAMED

    @staticmethod
    def canonical(host: str) -> str:
        """Return this machine's name for a loopback host, else ``host`` itself.

        A connection that declared no host is recorded as the address it arrived
        from, so an applet on this machine appears as ``127.0.0.1`` while its
        sibling declares the machine name. Both are the same machine.
        """
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host
        return LocalHost.name() if is_loopback else host
