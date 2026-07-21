"""The render-dashboard convenience request — metrics, charts, and a table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.render import FrameSpec, RenderRequest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["RenderDashboardRequest"]


class RenderDashboardRequest(BaseModel):
    """Metric cards, charts, and a summary table stacked into one scene.

    Every section is optional; the request composes whichever are present into a
    separator-joined element tree and delegates the install to ``render``. Chart
    configs are open wire shapes for the plot element codec (PY-TS-14 boundary).
    """

    scene_id: str
    metrics: list[dict[str, str]] | None = None  # None omits the metric row
    charts: list[dict[str, object]] | None = None  # None omits the charts
    table_columns: list[str] | None = None  # None omits the summary table
    table_rows: list[list[object]] | None = None  # None means an empty table body
    title: str | None = None
    frame_id: str | None = None
    frame_title: str | None = None

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> RenderDashboardRequest | OpError:
        """Validate raw arguments, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError(code="invalid_request", reason=exc.errors()[0]["msg"])

    def to_render_request(self) -> RenderRequest:
        """Compose every present section, separator-joined, into a render."""
        sections = self._sections()
        elements: list[dict[str, object]] = []
        for index, section in enumerate(sections):
            elements.extend(section)
            if index < len(sections) - 1:
                elements.append({"kind": "separator"})
        return RenderRequest(
            scene_id=self.scene_id,
            elements=elements,
            title=self.title,
            frame=FrameSpec(frame_id=self.frame_id, frame_title=self.frame_title),
        )

    def _sections(self) -> list[list[dict[str, object]]]:
        """Gather the element groups for every section that has content."""
        sections: list[list[dict[str, object]]] = []
        if self.metrics:
            sections.append(self._metric_section(self.metrics))
        if self.charts:
            sections.append(self._chart_section(self.charts))
        if self.table_columns is not None:
            sections.append(self._table_section(self.table_columns))
        return sections

    @staticmethod
    def _metric_section(
        metrics: Sequence[Mapping[str, str]],
    ) -> list[dict[str, object]]:
        """Build one columns group of label/value metric cards."""
        cards = [
            {
                "kind": "group",
                "id": f"metric-{i}",
                "children": [
                    {"kind": "text", "id": f"metric-label-{i}", "content": m["label"]},
                    {
                        "kind": "text",
                        "id": f"metric-value-{i}",
                        "content": m["value"],
                        "style": "heading",
                    },
                ],
            }
            for i, m in enumerate(metrics)
        ]
        return [
            {
                "kind": "group",
                "id": "metrics-row",
                "layout": "columns",
                "children": cards,
            }
        ]

    @staticmethod
    def _chart_section(
        charts: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        """Turn each chart config into a plot element, filling a missing id."""
        elements: list[dict[str, object]] = []
        for i, chart in enumerate(charts):
            plot: dict[str, object] = {**chart, "kind": "plot"}
            if "id" not in plot:
                plot["id"] = f"chart-{i}"
            elements.append(plot)
        return elements

    def _table_section(self, columns: Sequence[str]) -> list[dict[str, object]]:
        """Build the summary table element from the dashboard's columns and rows."""
        return [
            {
                "kind": "table",
                "id": "dashboard-table",
                "columns": list(columns),
                "rows": self.table_rows if self.table_rows is not None else [],
                "flags": ["borders", "row_bg"],
            }
        ]
