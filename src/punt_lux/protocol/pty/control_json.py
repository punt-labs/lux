"""The bounded JSON object every channel-zero control message is carried in."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from punt_lux.protocol.pty.control_fields import ControlError

MAX_CONTROL_BYTES = 16 * 1024


class ControlJson:
    """Encode and parse one control object, refusing anything ambiguous.

    Requests and session events share this frame: UTF-8, at most
    ``MAX_CONTROL_BYTES``, one top-level object, no duplicate keys and no
    non-finite numbers. What the object means is the caller's concern.
    """

    @classmethod
    def dump(cls, fields: Mapping[str, object]) -> bytes:
        data = json.dumps(
            fields, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        cls._check_size(data)
        return data

    @classmethod
    def parse(cls, data: bytes) -> dict[str, object]:
        """Return the object, or raise ``ControlError`` for any malformed frame."""
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
        return cast("dict[str, object]", raw)

    @staticmethod
    def _check_size(data: bytes) -> None:
        if not data or len(data) > MAX_CONTROL_BYTES:
            raise ControlError("control payload is empty or exceeds its size limit")

    @staticmethod
    def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Reject duplicate keys rather than silently choosing one authority."""
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ControlError("duplicate control field")
        return result

    @staticmethod
    def _reject_constant(value: str) -> object:
        raise ControlError(f"non-finite number {value}")
