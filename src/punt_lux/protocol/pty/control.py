"""Version-one JSON control messages carried by channel-zero DATA frames."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import ClassVar, Protocol, Self, cast, runtime_checkable

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.session_requests import KillRequest, ListRequest

MAX_CONTROL_BYTES = 16 * 1024
WIRE_VERSION = 1

type Request = HelloRequest | AttachRequest | ListRequest | KillRequest


@runtime_checkable
class ControlRequest(Protocol):
    """Structural contract; requests own their validation and serialization."""

    @property
    def request_id(self) -> int: ...

    def to_dict(self) -> dict[str, object]: ...

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self: ...


class ControlCodec:
    """Bounded UTF-8 JSON codec with a closed operation registry."""

    _DECODERS: ClassVar[dict[str, Callable[[Mapping[str, object]], Request]]] = {
        "hello": HelloRequest.from_dict,
        "attach": AttachRequest.from_dict,
        "list": ListRequest.from_dict,
        "kill": KillRequest.from_dict,
    }

    @classmethod
    def encode(cls, request: ControlRequest) -> bytes:
        data = json.dumps(
            request.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        cls._check_size(data)
        return data

    @classmethod
    def decode(cls, data: bytes) -> Request:
        cls._check_size(data)
        try:
            raw: object = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=cls._object,
                parse_constant=cls._reject_constant,
            )
        except (UnicodeError, ValueError) as error:
            raise ControlError(f"invalid control JSON: {error}") from error
        if not isinstance(raw, dict):
            raise ControlError("control message must be an object")
        # JSON object keys are strings; _object rejects duplicate keys.
        fields = cast("dict[str, object]", raw)
        operation = fields.get("op")
        if not isinstance(operation, str) or operation not in cls._DECODERS:
            raise ControlError("unknown control operation")
        return cls._DECODERS[operation](fields)

    @staticmethod
    def _check_size(data: bytes) -> None:
        if not data or len(data) > MAX_CONTROL_BYTES:
            raise ControlError("control payload is empty or exceeds its size limit")

    @staticmethod
    def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Reject duplicate keys rather than silently choosing one authority."""
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ControlError(f"duplicate field {key}")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value: str) -> object:
        raise ControlError(f"non-finite number {value}")
