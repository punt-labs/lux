"""FrameStatePatch — the change request for a frame's transient minimize state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["FrameStatePatch"]


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
