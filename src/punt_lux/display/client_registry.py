"""ClientRegistry -- the six per-fd maps (once ``SocketListener``'s own
parallel dicts) a connected client's state lives in, per PY-OO-5."""

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
        """Return the declared ``HubId`` for ``fd``, or ``None`` if unidentified."""
        return self._client_hub_ids.get(fd)

    def hub_fd_for(self, hub_id: HubId) -> int | None:
        """Return the live fd currently declaring ``kind="hub"`` with this ``HubId``.

        Keyed on ``HubId``, never on the declared ``name`` (W11) -- ``name`` is
        "what a human calls this connection," not a per-process identity, and
        every production Hub today declares the identical hardcoded name. Two
        Hubs sharing a name must coexist; two connections sharing a ``HubId``
        (a reconnect) must not.
        """
        for candidate_fd, kind in self._client_kinds.items():
            if kind == "hub" and self._client_hub_ids.get(candidate_fd) == hub_id:
                return candidate_fd
        return None

    def fd_for_hub_token(self, token: str) -> int | None:
        """Return the live ``kind="hub"`` fd declaring this ``HubId.wire_token``
        -- a menu's Hub, never a ``kind="test"`` probe standing in for none."""
        kinds, hub_ids = self._client_kinds, self._client_hub_ids
        hub_fds = filter(lambda fd: kinds[fd] == "hub", kinds)
        return next(filter(lambda fd: hub_ids[fd].wire_token == token, hub_fds), None)

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
        """Drop every connection's state, all six maps: shutdown, not one
        departure -- a reused listener must never inherit a departed identity."""
        self._readers.clear()
        self._fd_to_client.clear()
        self._client_names.clear()
        self._client_kinds.clear()
        self._client_hub_ids.clear()
        self._client_connect_times.clear()
