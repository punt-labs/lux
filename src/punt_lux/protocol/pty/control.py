"""JSON control requests and session events carried by channel-zero DATA frames."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import ClassVar, Protocol, Self, runtime_checkable

from punt_lux.protocol.pty.attach import AttachRequest as AttachRequest
from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.control_json import ControlJson
from punt_lux.protocol.pty.hello import HelloRequest as HelloRequest
from punt_lux.protocol.pty.new_request import NewRequest as NewRequest
from punt_lux.protocol.pty.session_events import (
    SessionEvent as SessionEvent,
    WatchRequest as WatchRequest,
)
from punt_lux.protocol.pty.session_requests import (
    KillRequest as KillRequest,
    ListRequest as ListRequest,
)

WIRE_VERSION = 4

type Request = (
    HelloRequest | AttachRequest | ListRequest | KillRequest | NewRequest | WatchRequest
)


@runtime_checkable
class ControlRequest(Protocol):
    """Structural contract; requests own their validation and serialization."""

    @property
    def request_id(self) -> int: ...

    def to_dict(self) -> dict[str, object]: ...

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self: ...


class ControlCodec:
    """Requests on channel zero, discriminated by ``op`` from a closed registry.

    Session events share the frame but carry ``event`` instead of ``op``, so
    this decoder refuses them (see ``SessionEvent.decode``).
    """

    _DECODERS: ClassVar[dict[str, Callable[[Mapping[str, object]], Request]]] = {
        "hello": HelloRequest.from_dict,
        "attach": AttachRequest.from_dict,
        "list": ListRequest.from_dict,
        "kill": KillRequest.from_dict,
        "new": NewRequest.from_dict,
        "watch": WatchRequest.from_dict,
    }

    @classmethod
    def encode(cls, request: ControlRequest) -> bytes:
        return ControlJson.dump(request.to_dict())

    @classmethod
    def decode(cls, data: bytes) -> Request:
        fields = ControlJson.parse(data)
        operation = fields.get("op")
        if not isinstance(operation, str) or operation not in cls._DECODERS:
            raise ControlError("unknown control operation")
        return cls._DECODERS[operation](fields)
