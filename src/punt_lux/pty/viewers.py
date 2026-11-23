"""Channel-indexed viewers; subscriptions never own the underlying program."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from punt_lux.pty.peer import Peer
from punt_lux.pty.repaint_failures import RepaintFailures
from punt_lux.pty.viewer_flow import ViewerFlow


@dataclass(frozen=True, slots=True)
class Binding:
    peer: Peer
    channel: int
    session: str
    flow: ViewerFlow
    repaints: RepaintFailures = field(default_factory=RepaintFailures)


class ViewerBindings:
    _channels: dict[int, Binding]
    _next_channel: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._channels = {}
        self._next_channel = 1
        return self

    @property
    def all(self) -> tuple[Binding, ...]:
        return tuple(self._channels.values())

    def add(self, peer: Peer, session: str, cols: int, rows: int) -> Binding:
        if any(binding.peer is peer for binding in self.session(session)):
            raise ValueError("peer already has this session attached")
        channel = self._next_channel
        if channel >= 1 << 32:
            raise ValueError("viewer channel ids exhausted; restart daemon")
        self._next_channel += 1
        flow = ViewerFlow(channel)
        flow.want_size(cols, rows)
        binding = Binding(peer, channel, session, flow)
        self._channels[channel] = binding
        return binding

    def session(self, name: str) -> tuple[Binding, ...]:
        return tuple(
            binding for binding in self._channels.values() if binding.session == name
        )

    def channel(self, peer: Peer, channel: int) -> Binding:
        binding = self._channels.get(channel)
        if binding is None or binding.peer is not peer:
            raise ValueError("unknown viewer channel")
        return binding

    def remove_channel(self, peer: Peer, channel: int) -> None:
        self.channel(peer, channel)
        del self._channels[channel]

    def detach(self, peer: Peer) -> None:
        self._channels = {
            channel: binding
            for channel, binding in self._channels.items()
            if binding.peer is not peer
        }

    def close_session(self, name: str, reason: str) -> None:
        for binding in self.session(name):
            binding.flow.finish(reason)
