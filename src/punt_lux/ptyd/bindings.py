"""Viewer-to-session associations, separate from process ownership."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Self

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.peer import Peer


@dataclass(frozen=True, slots=True)
class Binding:
    peer: Peer
    channel: int
    session: str


class ViewerBindings:
    """Stage two permits one viewer per session; several sessions per peer."""

    _by_session: dict[str, Binding]
    _next_channel: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_session = {}
        self._next_channel = 1
        return self

    def add(self, peer: Peer, session: str) -> Binding:
        if session in self._by_session:
            raise ValueError("session already has an attached viewer")
        binding = Binding(peer, self._next_channel, session)
        self._next_channel += 1
        self._by_session[session] = binding
        return binding

    def session(self, name: str) -> Binding | None:
        return self._by_session.get(name)

    def channel(self, peer: Peer, channel: int) -> Binding:
        for binding in self._by_session.values():
            if binding.peer is peer and binding.channel == channel:
                return binding
        raise ValueError("unknown viewer channel")

    def remove_channel(self, peer: Peer, channel: int) -> None:
        binding = self.channel(peer, channel)
        del self._by_session[binding.session]

    def remove_session(self, name: str) -> Binding | None:
        return self._by_session.pop(name, None)

    def detach(self, peer: Peer) -> None:
        self._by_session = {
            name: binding
            for name, binding in self._by_session.items()
            if binding.peer is not peer
        }

    def close_session(self, name: str, reason: str) -> None:
        binding = self.remove_session(name)
        if binding is not None:
            payload = json.dumps({"reason": reason}).encode()
            binding.peer.queue(Frame(binding.channel, FrameKind.CLOSE, payload))
