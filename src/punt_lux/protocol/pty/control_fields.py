"""Strict, bounded field validation at the local terminal control boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Self


class ControlError(ValueError):
    """A control message failed schema validation."""


class ControlFields:
    """One decoded JSON object, validated by the request type that owns it."""

    _raw: Mapping[str, object]

    def __new__(cls, raw: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        self._raw = raw
        return self

    def shape(self, operation: str, keys: frozenset[str]) -> None:
        """Reject missing fields, unknown fields and the wrong discriminator."""
        if frozenset(self._raw) != keys:
            raise ControlError(f"{operation}: fields must be {sorted(keys)}")
        if self._raw.get("op") != operation:
            raise ControlError(f"expected operation {operation}")

    def integer(self, key: str, minimum: int, maximum: int) -> int:
        value = self._raw.get(key)
        if type(value) is not int:
            raise ControlError(f"{key} must be an integer")
        if not minimum <= value <= maximum:
            raise ControlError(f"{key} is outside {minimum}..{maximum}")
        return value

    def text(self, key: str, maximum: int = 4096) -> str:
        value = self._raw.get(key)
        if not isinstance(value, str):
            raise ControlError(f"{key} must be a string")
        if len(value) > maximum or "\x00" in value:
            raise ControlError(f"{key} is too long or contains NUL")
        return value

    def request_id(self) -> int:
        """Channel-zero request ids are positive uint32 values."""
        return self.integer("id", 1, (1 << 32) - 1)

    def session(self) -> str:
        """Session names are identifiers, never paths or shell fragments."""
        value = self.text("session", 128)
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) is None:
            raise ControlError("session must be a nonempty identifier")
        return value
