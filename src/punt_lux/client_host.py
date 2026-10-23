"""ClientHost -- the host a connection was observed arriving from, as a value."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from starlette.requests import HTTPConnection

__all__ = ["UNOBSERVED", "ClientHost", "ClientHosts"]


@final
class ClientHost:
    """The host a transport reported for one contact, or the fact that it reported none.

    Starlette's ``client`` is the address of the accepted TCP socket -- the same
    on a request and on a WebSocket. It is read from there and from nowhere else:
    no forwarding header, no declaration (luxd turns uvicorn's ``proxy_headers``
    off so the socket peer is what the server reports).

    A value captured once, at the door, and carried with the contact: an
    in-process caller, stdio, or a server that reported no peer is
    :data:`UNOBSERVED`, and so is an empty address, which would otherwise join
    into a host list as a blank entry.
    """

    # "" = the contact was not observed; a real address is never empty.
    _host: str
    __slots__ = ("_host",)

    def __new__(cls, host: str) -> Self:
        self = super().__new__(cls)
        self._host = host
        return self

    @classmethod
    def of(cls, host: str | None) -> Self:
        """A reported address; ``None`` -- no peer reported -- is :data:`UNOBSERVED`."""
        return cls("" if host is None else host)

    @classmethod
    def of_connection(cls, connection: HTTPConnection) -> Self:
        """The host the connection's transport reported, read at the door."""
        client = connection.client
        return cls.of(None if client is None else client.host)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ClientHost):
            return NotImplemented
        return self._host == other._host

    def __hash__(self) -> int:
        return hash((ClientHost, self._host))

    def __repr__(self) -> str:
        return f"ClientHost({self._host!r})"

    @property
    def address(self) -> str:
        """The reported address; empty when the contact was not observed."""
        return self._host

    @property
    def observed(self) -> bool:
        """Whether a transport reported a host for this contact."""
        return bool(self._host)


@final
class ClientHosts:
    """The distinct hosts one session was reached from, in the order first seen.

    The rule of the collection lives here: a host already present is not
    repeated, and an unobserved contact adds nothing.
    """

    _names: tuple[str, ...]
    __slots__ = ("_names",)

    def __new__(cls, names: tuple[str, ...] = ()) -> Self:
        self = super().__new__(cls)
        self._names = names
        return self

    @property
    def names(self) -> tuple[str, ...]:
        """The hosts, first seen first."""
        return self._names

    def with_host(self, host: ClientHost) -> ClientHosts:
        """These hosts with ``host`` last, unless it is unobserved or already here."""
        if not host.observed or host.address in self._names:
            return self
        return ClientHosts((*self._names, host.address))


# The contact of a caller no transport observed: in-process, stdio, no peer reported.
UNOBSERVED = ClientHost("")
