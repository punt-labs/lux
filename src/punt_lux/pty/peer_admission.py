"""Who may be served: a peer that said hello with the versions this daemon speaks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.stream.control import WIRE_VERSION

if TYPE_CHECKING:
    from punt_lux.pty.peer import Peer
    from punt_lux.wire.stream.hello import HelloRequest


class PeerAdmission:
    """Admit a peer on a matching hello and refuse requests from one that skipped it."""

    _wire: int
    _snapshot: str

    def __new__(cls, wire: int, snapshot: str) -> Self:
        self = super().__new__(cls)
        self._wire, self._snapshot = wire, snapshot
        return self

    @classmethod
    def current(cls) -> Self:
        """Admit peers that speak this build's versions."""
        return cls(WIRE_VERSION, snapshot_version())

    def admit(self, peer: Peer, hello: HelloRequest) -> dict[str, object]:
        """Mark ``peer`` ready and return the hello reply body.

        Raises:
            ValueError: The hello names other wire or snapshot versions.
        """
        if (hello.version, hello.snapshot_version) != (self._wire, self._snapshot):
            raise ValueError("wire/model/snapshot mismatch; restart client and daemon")
        peer.mark_ready()
        return {"version": self._wire, "snapshot_version": self._snapshot}

    def require_ready(self, peer: Peer) -> None:
        """Refuse a session request from a peer that has not been admitted."""
        if not peer.ready:
            raise ValueError("hello must precede session requests")
