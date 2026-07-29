"""The typed wire frames of the persistent WebSocket listen leg.

A persistent client — a daemon holding one connection to luxd — speaks these
frames over the WebSocket. They are pydantic models discriminated by a ``kind``
tag, so a frame parses into exactly one shape and never a raw dict. The client
sends :class:`SubscribeFrame` and :class:`RenewFrame`; the Hub sends
:class:`ReadyFrame` on connect, :class:`EventFrame` for a subscribed topic's
publish, and :class:`CallbackFrame` for a menu click routed to this session.

Both ends share this module, so the client's send is the server's read and back:
:data:`ClientFrames` parses what the Hub receives, :data:`ServerFrames` parses
what the client receives, and each frame serializes itself with
``model_dump_json``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

__all__ = [
    "CallbackFrame",
    "ClientFrame",
    "ClientFrames",
    "EventFrame",
    "ReadyFrame",
    "RenewFrame",
    "ServerFrame",
    "ServerFrames",
    "SubscribeFrame",
]


class SubscribeFrame(BaseModel):
    """Ask the Hub to subscribe this connection to each named topic."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["subscribe"] = "subscribe"
    topics: tuple[str, ...]


class RenewFrame(BaseModel):
    """A keepalive: any frame renews the lease, and this one carries nothing else."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["renew"] = "renew"


# What the Hub receives from a persistent client, parsed to one shape by ``kind``.
ClientFrame = Annotated[SubscribeFrame | RenewFrame, Field(discriminator="kind")]
ClientFrames: TypeAdapter[SubscribeFrame | RenewFrame] = TypeAdapter(ClientFrame)


class ReadyFrame(BaseModel):
    """The handshake acknowledgement: the connection id the Hub bound this client to.

    The client reads it back to confirm the identity it declared resolved to the
    connection its REST-registered callbacks are held under — the two legs' shared
    key (see :func:`punt_lux.connection_identity.connection_for`).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["ready"] = "ready"
    connection_id: str


class EventFrame(BaseModel):
    """A pub-sub event delivered because this connection subscribed to ``topic``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["event"] = "event"
    topic: str
    # An open-ended agent payload; the wire boundary keeps it ``object``-valued
    # (PY-TS-14) rather than laundering an unknown schema as ``Any``.
    payload: dict[str, object]


class CallbackFrame(BaseModel):
    """A menu click routed to this session: the id of the callback that fired."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["callback"] = "callback"
    callback_id: str


# What a persistent client receives from the Hub, parsed to one shape by ``kind``.
ServerFrame = Annotated[
    ReadyFrame | EventFrame | CallbackFrame, Field(discriminator="kind")
]
ServerFrames: TypeAdapter[ReadyFrame | EventFrame | CallbackFrame] = TypeAdapter(
    ServerFrame
)
