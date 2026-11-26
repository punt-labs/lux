"""The one CLOSE frame a viewer is owed once everything before it is sent."""

from __future__ import annotations

from typing import Self

from punt_lux.wire.stream.control_json import ControlJson
from punt_lux.wire.stream.frames import Frame, FrameKind


class CloseNotice:
    """The one CLOSE frame a viewer is owed once everything before it is sent."""

    _payload: bytes
    _sent: bool

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._payload = b""
        self._sent = False
        return self

    @property
    def sent(self) -> bool:
        return self._sent

    def set(self, reason: str, exit_code: object) -> None:
        self._payload = ControlJson.dump({"reason": reason, "exit_code": exit_code})

    def take(self, channel: int) -> list[Frame]:
        """Return the CLOSE frame once, if one is set and not yet sent."""
        if not self._payload or self._sent:
            return []
        self._sent = True
        return [Frame(channel, FrameKind.CLOSE, self._payload)]
