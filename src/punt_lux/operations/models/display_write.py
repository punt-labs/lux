"""The frame-state change request and the display's acknowledgment of it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["FrameStateAck", "FrameStatePatch"]


class FrameStatePatch(BaseModel):
    """A change to a frame's transient minimize state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimized: bool | None = None  # None leaves the frame's minimize state as-is

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> FrameStatePatch | OpError:
        """Validate raw arguments, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError.from_validation(exc)

    def provided(self) -> dict[str, object]:
        """Return only the fields the caller set, in the display's param shape."""
        return self.model_dump(exclude_none=True)


class FrameStateAck(BaseModel):
    """The display's acknowledgment that it acted on a frame's state.

    Pins the real ``set_frame_state`` reply shape: the ``frame_id`` acted on and
    the ``changed`` map of fields the display actually flipped. A reply missing
    either, or carrying the wrong types, is a ``fault`` — never a fabricated
    success — so schema drift is caught instead of silently acknowledged.
    """

    model_config = ConfigDict(frozen=True)

    frame_id: str
    changed: dict[str, bool]  # the transient fields the display flipped

    @classmethod
    def from_reply(cls, payload: Mapping[str, object]) -> FrameStateAck | OpError:
        """Build from the display's ``set_frame_state`` reply, or reject it."""
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
