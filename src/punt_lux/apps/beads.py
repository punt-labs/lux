"""Beads Browser — display beads issues in a Lux frame.

Self-contained module with no imports from display.py, hooks.py, or
other Lux internals.  Designed to be extractable into the beads repo
as an optional dependency.

Data is fetched live from DoltDB via the ``bd list --json`` CLI command.

Public API:
    load_beads           — fetch and filter issues via ``bd list --json``
    build_beads_payload  — build a table element dict from issue data
    build_beads_elements — build display elements from issue data
    render_beads_board   — send the beads table to a LuxClient
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from punt_lux.protocol import Element, TextElement, element_from_dict

if TYPE_CHECKING:
    from punt_lux.client import LuxClient

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_FIELD_DEFAULTS: dict[str, Any] = {
    "title": "",
    "status": "open",
    "priority": 4,
    "issue_type": "task",
    "description": "",
    "owner": "",
    "created_at": "",
    "updated_at": "",
}


def load_beads(*, all_issues: bool = False) -> list[dict[str, Any]]:
    """Fetch, default-fill, filter, and sort beads issues via ``bd list --json``.

    Returns issues sorted with in_progress first, then by priority
    ascending, then by updated_at descending within equal groups.

    If the ``bd`` CLI is unavailable or the subprocess fails, returns ``[]``.
    """
    cmd: list[str] = ["bd", "list", "--json"]
    if all_issues:
        cmd.append("--all")
    else:
        cmd.extend(["--status=open,in_progress"])

    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, list):
        return []
    issues: list[dict[str, Any]] = []
    for entry in cast("list[Any]", raw):  # type: ignore[redundant-cast]
        if not isinstance(entry, dict):
            continue
        row = cast("dict[str, Any]", entry)
        for key, default in _FIELD_DEFAULTS.items():
            if row.get(key) is None:
                row[key] = default
        issues.append(row)

    # Three-pass stable sort: updated_at desc, then priority asc, then
    # in_progress floats to top.  Python's stable sort preserves earlier
    # orderings within equal keys at each pass.
    issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
    issues.sort(key=lambda i: i["priority"])
    issues.sort(key=lambda i: i["status"] != "in_progress")

    return issues


def build_beads_payload(
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the show_table element dict and metadata for beads issues.

    Returns a dict with keys: ``columns``, ``rows``, ``filters``, ``detail``,
    ready to be wrapped as a table element.
    """
    columns = ["ID", "Title", "Status", "P", "Type"]

    rows: list[list[Any]] = []
    detail_rows: list[list[str]] = []
    detail_bodies: list[str] = []
    statuses: set[str] = set()
    types: set[str] = set()

    for issue in issues:
        rows.append(
            [
                issue.get("id", ""),
                issue["title"],
                issue["status"],
                f"P{issue['priority']}",
                issue["issue_type"],
            ]
        )
        detail_rows.append(
            [
                issue.get("id", ""),
                issue["status"],
                f"P{issue['priority']}",
                issue["issue_type"],
                issue["owner"],
                issue["created_at"][:10],
                issue["updated_at"][:10],
            ]
        )
        detail_bodies.append(issue["description"] or "No description.")
        statuses.add(issue["status"])
        types.add(issue["issue_type"])

    filters = [
        {
            "type": "search",
            "column": [0, 1],
            "hint": "Filter by ID or title...",
        },
        {
            "type": "combo",
            "column": 2,
            "items": ["All", *sorted(statuses)],
            "label": "Status",
        },
        {
            "type": "combo",
            "column": 4,
            "items": ["All", *sorted(types)],
            "label": "Type",
        },
    ]

    detail = {
        "fields": [
            "ID",
            "Status",
            "Priority",
            "Type",
            "Owner",
            "Created",
            "Updated",
        ],
        "rows": detail_rows,
        "body": detail_bodies,
    }

    return {
        "columns": columns,
        "rows": rows,
        "filters": filters,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Rendering (uses LuxClient — the only Lux dependency)
# ---------------------------------------------------------------------------


def build_beads_elements(issues: list[dict[str, Any]]) -> list[Element]:
    """Build display elements for a beads issue list.

    Returns a list of protocol elements ready to pass to ``LuxClient.show()``.
    If *issues* is empty, returns a placeholder text element.
    """
    if not issues:
        return [TextElement(id="empty", content="No active issues.")]

    payload = build_beads_payload(issues)
    table = element_from_dict(
        {
            "kind": "table",
            "id": "table",
            "columns": payload["columns"],
            "rows": payload["rows"],
            "flags": ["borders", "row_bg", "resizable", "sortable", "copy_id"],
            "filters": payload["filters"],
            "detail": payload["detail"],
        }
    )
    return [table]


def render_beads_board(client: LuxClient) -> None:
    """Send the beads issue board to the display via *client*.

    Fetches live data from DoltDB via ``bd list --json``.  If the command
    fails or returns no issues, renders a placeholder message.  Uses
    ``show_async`` so the call is non-blocking (safe to call from a menu
    callback thread).
    """
    project = Path.cwd().name or "unknown"
    frame_id = f"beads-{project}"

    issues = load_beads()

    client.show_async(
        f"beads-{project}",
        elements=build_beads_elements(issues),
        frame_id=frame_id,
        frame_title=f"Beads: {project}",
    )
