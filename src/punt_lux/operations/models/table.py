"""The render-table convenience request — parsed into a table composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.render import FrameSpec, RenderRequest
from punt_lux.protocol.compositions import TableCompositionSpec

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.scene_presentation import ScenePresentation

__all__ = ["RenderTableRequest"]


class RenderTableRequest(BaseModel):
    """A searchable table with optional categorical filters and drill-down detail.

    Filters and detail are open wire shapes (PY-TS-14 wire boundary) the
    composition reads by key; this request parses the tool arguments and hands a
    ``TableCompositionSpec`` plus a scene presentation to ``render_table``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: str
    columns: list[str]
    rows: list[list[object]]
    filters: list[dict[str, object]] | None = None  # None omits the filter bar
    detail: dict[str, object] | None = None  # None omits the detail panel
    flags: list[str] | None = None  # None uses the default border/row-bg flags
    title: str | None = None
    frame_id: str | None = None
    frame_title: str | None = None

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> RenderTableRequest | OpError:
        """Validate raw arguments, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError.from_validation(exc)

    def to_spec(self) -> TableCompositionSpec:
        """Return the composition spec this request builds its element tree from."""
        return TableCompositionSpec(
            columns=tuple(self.columns),
            rows=tuple(tuple(row) for row in self.rows),
            filters=tuple(self.filters) if self.filters is not None else (),
            detail=self.detail,
            flags=tuple(self.flags) if self.flags is not None else None,
        )

    def presentation(self) -> ScenePresentation:
        """Return the frame presentation this scene renders into."""
        return self._shell().presentation()

    def frame_ttl(self) -> float | None:
        """Return the frame's TTL in seconds, or None for a permanent frame."""
        return self._shell().frame_ttl()

    def _shell(self) -> RenderRequest:
        """Return a presentation-only render request (the frame, no elements)."""
        return RenderRequest(
            scene_id=self.scene_id,
            elements=[],
            title=self.title,
            frame=FrameSpec(frame_id=self.frame_id, frame_title=self.frame_title),
        )
