"""The render-table convenience request — a table scene composed for ``render``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.render import FrameSpec, RenderRequest

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["RenderTableRequest"]

_DEFAULT_FLAGS = ("borders", "row_bg")


class RenderTableRequest(BaseModel):
    """A filterable table with optional filters and drill-down detail.

    Filters and detail are open wire shapes consumed by the table element codec
    (PY-TS-14 wire boundary); this request composes them into one table element
    and delegates the actual install to ``render``.
    """

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
            return OpError(code="invalid_request", reason=exc.errors()[0]["msg"])

    def to_render_request(self) -> RenderRequest:
        """Compose the table element and wrap it in a whole-scene render."""
        table: dict[str, object] = {
            "kind": "table",
            "id": "table",
            "columns": self.columns,
            "rows": self.rows,
            "flags": self.flags if self.flags is not None else list(_DEFAULT_FLAGS),
        }
        if self.filters is not None:
            table["filters"] = self.filters
        if self.detail is not None:
            table["detail"] = self.detail
        return RenderRequest(
            scene_id=self.scene_id,
            elements=[table],
            title=self.title,
            frame=FrameSpec(frame_id=self.frame_id, frame_title=self.frame_title),
        )
