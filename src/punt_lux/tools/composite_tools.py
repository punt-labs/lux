"""Convenience MCP tools composed over ``show()``.

``show_table`` and ``show_dashboard`` are not new capabilities — they are common
layouts (a filterable table with drill-down detail; metric cards over charts over
a summary table) assembled from the same element tree ``show()`` renders. They
live apart from the core display tools so the one-universal-render surface stays
legible and this module carries only the composed patterns. Each registers on the
shared FastMCP instance and delegates straight to the operations facade, exactly
as the core tools do.
"""

from __future__ import annotations

import asyncio
from typing import Any

from punt_lux.commands import (
    Ctx as CommandCtx,
    SceneOps,
    scene_dashboard as scene_dashboard_command,
    scene_table as scene_table_command,
)
from punt_lux.operations import RenderDashboardRequest, RenderTableRequest
from punt_lux.tools import tools as _core
from punt_lux.tools.server import mcp

__all__ = ["show_dashboard", "show_table"]

# ``_core.OPERATIONS`` is read at call time, never imported by value: tests
# rebind ``punt_lux.tools.tools.OPERATIONS`` to route a wrapper at an isolated
# store, and a value-import would freeze the production facade past that rebind.


@mcp.tool()
def show_table(
    scene_id: str,
    columns: list[str],
    rows: list[list[Any]],
    filters: list[dict[str, Any]] | None = None,
    detail: dict[str, Any] | None = None,
    flags: list[str] | None = None,
    key_column: int | str = 0,
    table_id: str | None = None,
    title: str | None = None,
    frame_id: str | None = None,
    frame_title: str | None = None,
) -> str:
    """Display a filterable data table with optional detail panel.

    This is a convenience wrapper around ``show()`` for the most common
    pattern: a searchable, filterable table with drill-down detail. The
    Hub composes a search box, status combos, the grid, and a
    selection-bound detail panel from primitives; filtering and detail
    binding run Hub-side (the packaged default), so a selection hidden by
    a filter reappears when the filter is cleared.

    Args:
        scene_id: Unique identifier for this scene.
        columns: Column headers (e.g., ["ID", "Title", "Status"]).
        rows: Table data — each row is a list matching columns order.
        filters: Built-in filter controls rendered above the table.
            Two types:
              Search:  {"type": "search", "column": [0, 1],
                        "hint": "Filter by ID or title..."}
              Combo:   {"type": "combo", "column": 2, "label": "Status",
                        "items": ["All", "Open", "Closed"]}
            First combo item should be "All" (no filter). Include only
            values that exist in the data. 1-3 filters is ideal.
        detail: Drill-down panel shown when a row is selected.
            Structure:
              {"fields": ["ID", "Status", "Priority"],
               "rows": [["ISS-1", "Open", "P1"], ...],
               "body": ["Full description for row 1...", ...]}
            ``detail.rows`` **and** ``detail.body`` must both be
            parallel to ``rows`` (same count, same order). Each
            entry in ``detail.body`` is the expanded text for the
            corresponding row.
        flags: Table flags (default: ["borders", "row_bg"]).
            Available: "borders", "row_bg", "resizable", "sortable",
            "copy_id" (copy first column to clipboard on row select).
        key_column: The column whose value is each row's stable id — a
            column index or a column name (default: 0, the first column).
            Selection and detail address rows by this id, so it survives a
            reorder. Pick a column with unique, non-empty values.
        table_id: Identity of the composed table within the scene (default:
            "table"). Set a distinct id for each table when a scene holds
            more than one, so their synthesized control ids do not collide.
        title: Window title.
        frame_id: Target frame for tab isolation (e.g., "beads-lux").
        frame_title: Display title for the frame (e.g., "Beads: lux").

    Example — issue explorer with search, status filter, and detail::

        show_table(
            scene_id="issues",
            columns=["ID", "Title", "Status", "Priority"],
            rows=[
                ["ISS-1", "Fix login timeout", "Open", "P1"],
                ["ISS-2", "Add dark mode", "In Progress", "P2"],
            ],
            filters=[
                {"type": "search", "column": [0, 1],
                 "hint": "Filter by ID or title..."},
                {"type": "combo", "column": 2, "label": "Status",
                 "items": ["All", "Open", "In Progress"]},
            ],
            detail={
                "fields": ["ID", "Status", "Priority", "Assignee"],
                "rows": [
                    ["ISS-1", "Open", "P1", "alice"],
                    ["ISS-2", "In Progress", "P2", "bob"],
                ],
                "body": [
                    "Login flow times out after 30s on slow connections.",
                    "Add system-wide dark mode toggle.",
                ],
            },
            title="Issue Explorer",
        )
    """
    request = RenderTableRequest.parse(
        {
            "scene_id": scene_id,
            "columns": columns,
            "rows": rows,
            "filters": filters,
            "detail": detail,
            "flags": flags,
            "key_column": key_column,
            "table_id": table_id,
            "title": title,
            "frame_id": frame_id,
            "frame_title": frame_title,
        }
    )
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(scene_table_command(ctx, request, scope=_core._scope()))
    return result.text


@mcp.tool()
def show_dashboard(
    scene_id: str,
    metrics: list[dict[str, str]] | None = None,
    charts: list[dict[str, Any]] | None = None,
    table_columns: list[str] | None = None,
    table_rows: list[list[Any]] | None = None,
    title: str | None = None,
    frame_id: str | None = None,
    frame_title: str | None = None,
) -> str:
    """Display a dashboard with metric cards, charts, and a data table.

    This is a convenience wrapper around ``show()`` for the dashboard
    pattern: metric cards across the top, charts in the middle, and a
    summary table at the bottom. All sections are optional — include
    only the ones relevant to your data.

    Args:
        scene_id: Unique identifier for this scene.
        metrics: Key-value metric cards displayed in a row.
            Each dict: {"label": "Total Users", "value": "1,234"}.
            2-5 cards is ideal for a single-glance overview.
        charts: Plot elements displayed below the metrics.
            Each dict is a plot config:
              {"id": "p1", "title": "Trend",
               "x_label": "Time", "y_label": "Value",
               "series": [{"label": "requests", "type": "line",
                           "x": [1,2,3], "y": [10,20,15]}]}
            Series types: "line" (trends), "bar" (comparisons),
            "scatter" (correlations).
        table_columns: Column headers for the summary table.
        table_rows: Rows for the summary table.
        title: Window title.

    Example — test results dashboard::

        show_dashboard(
            scene_id="test-results",
            metrics=[
                {"label": "Total", "value": "142"},
                {"label": "Passed", "value": "137"},
                {"label": "Failed", "value": "5"},
                {"label": "Duration", "value": "2m 34s"},
            ],
            charts=[{
                "id": "duration-chart",
                "title": "Test Duration by Suite",
                "x_label": "Suite", "y_label": "Seconds",
                "series": [{"label": "duration", "type": "bar",
                            "x": [1, 2, 3],
                            "y": [45, 82, 27]}],
            }],
            table_columns=["Test", "Status", "Duration"],
            table_rows=[
                ["test_login", "PASS", "1.2s"],
                ["test_upload", "FAIL", "5.0s"],
            ],
            title="Test Results",
        )
    """
    request = RenderDashboardRequest.parse(
        {
            "scene_id": scene_id,
            "metrics": metrics,
            "charts": charts,
            "table_columns": table_columns,
            "table_rows": table_rows,
            "title": title,
            "frame_id": frame_id,
            "frame_title": frame_title,
        }
    )
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(scene_dashboard_command(ctx, request, scope=_core._scope()))
    return result.text
