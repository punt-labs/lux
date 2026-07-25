"""The render request and the frame presentation it carries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from punt_lux.domain.hub.scene_presentation import SceneLayout, ScenePresentation
from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["FrameFlags", "FrameSpec", "RenderRequest"]


class FrameFlags(BaseModel):
    """ImGui window flags a scene's frame may carry; unknown keys are ignored.

    ``extra="ignore"`` mirrors the legacy path, which silently dropped unknown flags.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    no_resize: bool = False
    no_collapse: bool = False
    auto_resize: bool = False
    no_title_bar: bool = False
    no_background: bool = False
    no_scrollbar: bool = False


class FrameSpec(BaseModel):
    """Where and how a scene is shown into its frame; every field defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    frame_id: str | None = None  # None defaults to the scene id
    frame_title: str | None = None  # None defaults to the title, then the scene id
    size: tuple[int, int] | None = None  # None lets the display choose
    flags: FrameFlags | None = None  # None means no window flags
    layout: Literal["tab", "stack"] | None = None  # None uses the display default
    # None is the "permanent" state (PY-TS-14): the frame never expires unless a
    # re-show arms a TTL. A set value must be positive; zero/negative is rejected.
    ttl_seconds: float | None = Field(default=None, gt=0)


class RenderRequest(BaseModel):
    """A whole scene to install: its id, its element tree, and its frame."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: str
    # Wire element trees. dict-shaped because element kinds are open and each
    # self-validates via the element codec and the submission gate inside the
    # operation (PY-TS-14 wire boundary).
    elements: list[dict[str, object]]
    title: str | None = None  # None shows the scene id as the frame title
    layout: SceneLayout = "single"
    frame: FrameSpec | None = None  # None synthesizes a default frame at render

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> RenderRequest | OpError:
        """Validate raw arguments, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError(code="invalid_request", reason=cls._reason_for(exc))

    @staticmethod
    def _reason_for(exc: ValidationError) -> str:
        """Render the first validation failure as its bare legacy message."""
        err = exc.errors()[0]
        loc = err["loc"]
        value = err.get("input")
        if loc == ("layout",):
            return f"layout must be single/rows/columns/grid, got {value!r}"
        if loc == ("frame", "layout"):
            return f"frame_layout must be 'tab' or 'stack', got {value!r}"
        if loc[:2] == ("frame", "size"):
            return "frame_size must be [width, height]"
        if loc == ("frame", "ttl_seconds"):
            return f"frame_ttl_seconds must be a positive number, got {value!r}"
        return OpError.describe(err)

    def frame_ttl(self) -> float | None:
        """Return the frame's TTL in seconds, or None for a permanent frame (PY-TS-14).

        The Hub arms a deadline only for a positive TTL; a re-show with no TTL
        clears any prior one, so None is the "permanent" contract, not "expire now".
        """
        return self.frame.ttl_seconds if self.frame is not None else None

    def _resolved_frame(self) -> FrameSpec:
        """Return the named frame, or synthesize a default one when none was named.

        Where "every scene is framed" is guaranteed: an unnamed frame becomes a
        default ``FrameSpec`` whose ``frame_id`` resolves to the scene id below.
        """
        return self.frame if self.frame is not None else FrameSpec()

    def presentation(self) -> ScenePresentation:
        """Build the total presentation this scene renders into, framed by default."""
        frame = self._resolved_frame()
        return ScenePresentation(
            frame_id=frame.frame_id if frame.frame_id is not None else self.scene_id,
            title=self.title,
            layout=self.layout,
            frame_title=(
                frame.frame_title
                if frame.frame_title is not None
                else (self.title or self.scene_id)
            ),
            frame_size=frame.size,
            frame_flags=frame.flags.model_dump() if frame.flags is not None else None,
            frame_layout=frame.layout,
        )
