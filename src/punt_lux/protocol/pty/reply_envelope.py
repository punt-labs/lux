"""Bounded JSON envelopes and typed failure metadata for control replies."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields
from punt_lux.protocol.pty.control_json import MAX_CONTROL_BYTES


class ReplyEnvelope(ControlFields):
    def failure(self) -> bool:
        keys = frozenset(self._raw)
        required = frozenset({"id", "ok", "error"})
        retryable = self._raw.get("retryable", False)
        if (
            keys not in (required, required | {"retryable"})
            or self._raw.get("ok") is not False
            or type(retryable) is not bool
        ):
            raise ControlError("invalid failure envelope")
        return retryable

    @staticmethod
    def encode(raw: Mapping[str, object]) -> bytes:
        data = json.dumps(dict(raw), ensure_ascii=False, allow_nan=False).encode()
        if not data or len(data) > MAX_CONTROL_BYTES:
            raise ControlError("reply exceeds control size limit")
        return data

    @staticmethod
    def decode(data: bytes) -> Mapping[str, object]:
        if not data or len(data) > MAX_CONTROL_BYTES:
            raise ControlError("reply exceeds control size limit")
        try:
            raw: object = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=ReplyEnvelope._object,
                parse_constant=ReplyEnvelope._reject_constant,
            )
        except (UnicodeError, ValueError) as error:
            raise ControlError("invalid reply JSON") from error
        if not isinstance(raw, dict):
            raise ControlError("reply must be an object")
        return cast("dict[str, object]", raw)

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
