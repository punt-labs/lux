"""Success and failure envelopes for channel-zero control requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self, cast

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.reply_envelope import ReplyEnvelope


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
        return cls(ReplyEnvelope(raw).request_id(), cast("dict[str, object]", result))


@dataclass(frozen=True, slots=True)
class FailureReply:
    request_id: int
    error: str
    retryable: bool = False

    def to_dict(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "id": self.request_id,
            "ok": False,
            "error": self.error,
        }
        return dict(fields, retryable=self.retryable)

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        fields = ReplyEnvelope(raw)
        retryable = fields.failure()
        return cls(fields.request_id(), fields.text("error", 4096), retryable)


type Reply = SuccessReply | FailureReply


class ReplyCodec:
    """Control envelopes contain bounded JSON, never terminal snapshot bytes."""

    @staticmethod
    def encode(reply: Reply) -> bytes:
        return ReplyEnvelope.encode(reply.to_dict())

    @staticmethod
    def decode(data: bytes) -> Reply:
        fields = ReplyEnvelope.decode(data)
        if fields.get("ok") is True:
            return SuccessReply.from_dict(fields)
        return FailureReply.from_dict(fields)
