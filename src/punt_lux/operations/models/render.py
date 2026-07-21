"""The render request and the frame presentation it carries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ValidationError

from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["FrameFlags", "FrameSpec", "RenderRequest"]


class FrameFlags(BaseModel):
    """The ImGui window flags a scene's frame may carry."""

    no_resize: bool = False
    no_collapse: bool = False
    auto_resize: bool = False
    no_title_bar: bool = False
    no_background: bool = False
    no_scrollbar: bool = False


class FrameSpec(BaseModel):
    """Where and how a scene is shown into its frame; every field defaults."""

    frame_id: str | None = None  # None defaults to the scene id
    frame_title: str | None = None  # None defaults to the title, then the scene id
    size: tuple[int, int] | None = None  # None lets the display choose
    flags: FrameFlags | None = None  # None means no window flags
    layout: Literal["tab", "stack"] | None = None  # None uses the display default


class RenderRequest(BaseModel):
    """A whole scene to install: its id, its element tree, and its frame."""

    scene_id: str
    # Wire element trees. dict-shaped because element kinds are open and each
    # self-validates via the element codec and the submission gate inside the
    # operation (PY-TS-14 wire boundary).
    elements: list[dict[str, object]]
    title: str | None = None  # None shows the scene id as the frame title
    layout: Literal["single", "rows", "columns", "grid"] = "single"
    frame: FrameSpec | None = None  # None means a default single-scene frame

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> RenderRequest | OpError:
        """Validate raw arguments, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError(code="invalid_request", reason=cls._reason_for(exc))

    @staticmethod
    def _reason_for(exc: ValidationError) -> str:
        """Render the first validation failure as its legacy status message."""
        err = exc.errors()[0]
        loc = err["loc"]
        value = err.get("input")
        if loc == ("layout",):
            return f"layout must be single/rows/columns/grid, got {value!r}"
        if loc == ("frame", "layout"):
            return f"frame_layout must be 'tab' or 'stack', got {value!r}"
        if loc[:2] == ("frame", "size"):
            return "frame_size must be [width, height]"
        return err["msg"]

    def presentation(self) -> ScenePresentation:
        """Build the frame presentation, resolving frame id and title defaults."""
        frame = self.frame if self.frame is not None else FrameSpec()
        frame_id = frame.frame_id if frame.frame_id is not None else self.scene_id
        frame_title = (
            frame.frame_title
            if frame.frame_title is not None
            else (self.title or self.scene_id)
        )
        return ScenePresentation(
            frame_id=frame_id,
            title=self.title,
            layout=self.layout,
            frame_title=frame_title,
            frame_size=frame.size,
            frame_flags=frame.flags.model_dump() if frame.flags is not None else None,
            frame_layout=frame.layout,
        )
