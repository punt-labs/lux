"""ClientRegistry -- the per-fd maps a connected client's state was split across.

``SocketListener`` held six parallel dicts -- readers, fd-to-socket, names,
kinds, Hub ids, connect times -- all keyed by the identical fd, each one
populated and popped by hand in lockstep. A cluster of parallel dicts keyed on
one domain entity's id is PY-OO-5's exact trigger: the entity (a connected
client) owns this data, not six maps a caller keeps in step by convention.
This class is that entity's registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.protocol import FrameReader

if TYPE_CHECKING:
    import socket

    from punt_lux.domain.hub_id import HubId

__all__ = ["ClientRegistry"]


@final
class ClientRegistry:
    """Own every per-fd map a connected client's state lives in."""

    _fd_to_client: dict[int, socket.socket]
    _readers: dict[int, FrameReader]
    _client_names: dict[int, str]
    _client_kinds: dict[int, Literal["hub", "test"]]
    _client_hub_ids: dict[int, HubId]
    _client_connect_times: dict[int, float]
    __slots__ = (
        "_client_connect_times",
        "_client_hub_ids",
        "_client_kinds",
        "_client_names",
        "_fd_to_client",
        "_readers",
    )

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._fd_to_client = {}
        self._readers = {}
        self._client_names = {}
        self._client_kinds = {}
        self._client_hub_ids = {}
        self._client_connect_times = {}
        return self

    @property
    def client_names(self) -> dict[int, str]:
        """Return fd-to-display-name mapping."""
        return self._client_names

    @property
    def client_connect_times(self) -> dict[int, float]:
        """Return fd-to-connect-timestamp mapping."""
        return self._client_connect_times

    @property
    def fd_to_client(self) -> dict[int, socket.socket]:
        """Return fd-to-socket mapping for O(1) lookup."""
        return self._fd_to_client

    def register_connection(self, fd: int, sock: socket.socket) -> None:
        """Record a freshly accepted connection and give it a fresh reader."""
        self._readers[fd] = FrameReader()
        self._fd_to_client[fd] = sock

    def reader_for(self, fd: int) -> FrameReader | None:
        """Return this fd's reader, or ``None`` once it has been forgotten."""
        return self._readers.get(fd)

    def identify(
        self,
        fd: int,
        *,
        kind: Literal["hub", "test"],
        name: str,
        hub_id: HubId,
        connect_time: float,
    ) -> None:
        """Record a client's declared kind, name, ``HubId``, and connect time."""
        self._client_names[fd] = name
        self._client_kinds[fd] = kind
        self._client_hub_ids[fd] = hub_id
        self._client_connect_times[fd] = connect_time

    def kind_of(self, fd: int) -> Literal["hub", "test"] | None:
        """Return the declared kind for ``fd``, or ``None`` before it identifies."""
        return self._client_kinds.get(fd)

    def hub_id_of(self, fd: int) -> HubId | None:
        """Return the declared ``HubId`` for ``fd``, or ``None`` before it identifies.

        Every ``kind`` populates a real ``HubId`` at identify time (`system.tex`
        "Hub Identity on the Wire") -- ``None`` here answers only "this fd has
        not yet sent a ``ConnectMessage``," never "identified with no identity."
        """
        return self._client_hub_ids.get(fd)

    def hub_fd_for(self, name: str) -> int | None:
        """Return the live fd currently declaring ``kind="hub"`` with this name.

        ``None`` when no such connection exists — the ordinary case once a
        superseded Hub's socket has already closed on its own.
        """
        for candidate_fd, kind in self._client_kinds.items():
            if kind == "hub" and self._client_names.get(candidate_fd) == name:
                return candidate_fd
        return None

    def forget_connection(self, fd: int) -> None:
        """Drop everything but the ``HubId`` -- a caller may still resolve it once."""
        self._readers.pop(fd, None)
        self._fd_to_client.pop(fd, None)
        self._client_names.pop(fd, None)
        self._client_kinds.pop(fd, None)
        self._client_connect_times.pop(fd, None)

    def forget_hub_id(self, fd: int) -> None:
        """Drop the last surviving fact about ``fd``, once nothing needs it."""
        self._client_hub_ids.pop(fd, None)

    def clear(self) -> None:
        """Drop every connection's state -- shutdown, not one departure."""
        self._readers.clear()
        self._fd_to_client.clear()
