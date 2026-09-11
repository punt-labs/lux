"""DisplayDialer -- the structural contract every Hub-to-Display transport meets.

The one thing :class:`~punt_lux.domain.hub.display_link.DisplayLink` needs from
a transport, whichever leg: dial once, get back a live socket that has already
exchanged ``ReadyMessage``/``ConnectMessage``. The socket family and any TLS
wrapping are the dialer's own business (``system.tex`` §"Connect, cross-host":
the Hub's connection code differs only in how it reaches the Display, not in
what it sends once connected). The ``AF_UNIX``
:class:`~punt_lux.domain.hub.handshake_connector.HandshakeConnector` and the
cross-host :class:`~punt_lux.domain.hub.cross_host_connector.CrossHostConnector`
both satisfy it -- families share by Protocol, not a base class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult

__all__ = ["DisplayDialer"]


@runtime_checkable
class DisplayDialer(Protocol):
    """Opens a connection to the Display and runs the connect handshake."""

    def dial(self, connect_timeout: float) -> HandshakeResult:
        """Open the Display connection and complete the handshake, or raise.

        Raises :class:`DisplayNotConnectedError` on any failure to reach the
        Display or complete the ``ReadyMessage``/``ConnectMessage`` exchange;
        the opened socket is closed on every failure path.
        """
        ...
