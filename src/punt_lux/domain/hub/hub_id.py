"""HubId -- a Hub connection's own stable identity, declared on the wire.

The first rung above a connection a Display can aggregate more than one of:
distinct not merely from another process on the same machine, but from a Hub
on a different machine entirely, per the operator's cross-host ruling.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Self, final

from punt_lux.domain.hub.id_separator import ID_SEPARATOR

__all__ = ["HubId"]

# RFC 2606 reserves ``.invalid`` for exactly this: a hostname that can never
# resolve, so a stub identity can never collide with a real HubId.current().
_STUB_HOSTNAME = "test.invalid"
_STUB_PID = 0


@final
@dataclass(frozen=True, slots=True)
class HubId:
    """A Hub connection's own stable identity -- network host plus process.

    Two independent uniqueness axes, kept as two fields because they are
    disambiguated by two different mechanisms: ``hostname`` distinguishes one
    machine from another (FQDN via :func:`socket.getfqdn`, not
    :func:`socket.gethostname` -- a bare hostname is not guaranteed unique
    across a network the way it is on one box); ``pid`` distinguishes one
    process from another on the same machine, the same shape of fix
    ``AppletIdentity`` already uses for two applets sharing one session
    (DES-067's ``#{session_pid}`` token). ``pid`` is not network-meaningful
    and only ever breaks a tie within one already-identified host.
    Self-reporting its own FQDN is as far as this class goes, and it is
    trustworthy on the ``AF_UNIX`` leg only because the socket directory's
    ``0700`` permission already bounds who can open a connection to declare a
    HubId in the first place -- that argument does not carry across a
    network, which is exactly why cross-host needs mTLS.
    """

    hostname: str
    pid: int

    @classmethod
    def current(cls) -> Self:
        """This process's own HubId, as declared to the Display."""
        return cls(socket.getfqdn(), os.getpid())

    @classmethod
    def stub(cls) -> Self:
        """A synthetic identity for a same-host ``kind="test"`` connection.

        A test connection is a stand-in for a Hub on the ``AF_UNIX`` leg --
        it runs the identical accept path and the identical
        ``ReadyMessage``/``ConnectMessage`` exchange a real Hub does, so it
        presents a HubId exactly as a real Hub does, never an absence of
        one. Built the same way :meth:`current` builds a real identity, with
        a hostname that can never resolve and so can never collide with one.
        """
        return cls(_STUB_HOSTNAME, _STUB_PID)

    @property
    def wire_token(self) -> str:
        """The string this identity declares on the wire.

        Compared for equality only, never parsed.
        """
        return f"{self.hostname}{ID_SEPARATOR}{self.pid}"
