"""Success and failure envelopes for channel-zero control requests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self, cast

from punt_lux.protocol.pty.control import MAX_CONTROL_BYTES
from punt_lux.protocol.pty.control_fields import ControlError, ControlFields


@dataclass(frozen=True, slots=True)
class SuccessReply:
    request_id: int
    result: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.request_id, "ok": True, "result": dict(self.result)}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        if (
            frozenset(raw) != frozenset({"id", "ok", "result"})
            or raw.get("ok") is not True
        ):
            raise ControlError("invalid success envelope")
        result = raw.get("result")
        if not isinstance(result, dict):
            raise ControlError("reply result must be an object")
        return cls(ControlFields(raw).request_id(), cast("dict[str, object]", result))


@dataclass(frozen=True, slots=True)
class FailureReply:
    request_id: int
    error: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.request_id, "ok": False, "error": self.error}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        if (
            frozenset(raw) != frozenset({"id", "ok", "error"})
            or raw.get("ok") is not False
        ):
            raise ControlError("invalid failure envelope")
        fields = ControlFields(raw)
        return cls(fields.request_id(), fields.text("error", 4096))


type Reply = SuccessReply | FailureReply


class ReplyCodec:
    """Control envelopes contain bounded JSON, never terminal snapshot bytes."""

    @staticmethod
    def encode(reply: Reply) -> bytes:
        data = json.dumps(reply.to_dict(), ensure_ascii=False, allow_nan=False).encode()
        if not data or len(data) > MAX_CONTROL_BYTES:
            raise ControlError("reply exceeds control size limit")
        return data

    @staticmethod
    def decode(data: bytes) -> Reply:
        if not data or len(data) > MAX_CONTROL_BYTES:
            raise ControlError("reply exceeds control size limit")
        try:
            raw: object = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=ReplyCodec._object,
                parse_constant=ReplyCodec._reject_constant,
            )
        except (UnicodeError, ValueError) as error:
            raise ControlError("invalid reply JSON") from error
        if not isinstance(raw, dict):
            raise ControlError("reply must be an object")
        fields = cast("dict[str, object]", raw)
        if fields.get("ok") is True:
            return SuccessReply.from_dict(fields)
        return FailureReply.from_dict(fields)

    @staticmethod
    def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ControlError(f"duplicate reply field {key}")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value: str) -> object:
        raise ControlError(f"non-finite reply value {value}")
