"""Beads Browser — display beads issues in a Lux frame.

Self-contained module with no imports from display.py, hooks.py, or
other Lux internals.  Designed to be extractable into the beads repo
as an optional dependency.

Public API:
    load_beads          — read and filter issues from .beads/issues.jsonl
    build_beads_payload — build a table element dict from issue data
    render_beads_board  — send the beads table to a LuxClient
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from punt_lux.protocol import TextElement, element_from_dict

if TYPE_CHECKING:
    from punt_lux.client import LuxClient

# ---------------------------------------------------------------------------
# Data loading (pure, testable)
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = frozenset({"open", "in_progress"})

_FIELD_DEFAULTS: dict[str, Any] = {
    "title": "",
    "status": "open",
    "priority": 4,
    "issue_type": "task",
    "description": "",
    "assignee": "",
    "owner": "",
    "created_at": "",
    "updated_at": "",
}


def load_beads(beads_dir: Path, *, all_issues: bool = False) -> list[dict[str, Any]]:
    """Read, default-fill, filter, and sort beads issues.

    Returns issues sorted with in_progress first, then by priority
    ascending, then by updated_at descending within equal groups.
    """
    path = beads_dir / "issues.jsonl"
    if not path.is_file():
        return []

    issues: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            issue = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"Malformed JSON in {path} at line {lineno}: {exc.msg}"
            raise ValueError(msg) from exc
        if not isinstance(issue, dict):
            msg = (
                f"Expected JSON object in {path} at line {lineno}, "
                f"got {type(issue).__name__}"
            )
            raise ValueError(msg)
        row = cast("dict[str, Any]", issue)
        for key, default in _FIELD_DEFAULTS.items():
            if row.get(key) is None:
                row[key] = default
        issues.append(row)

    if not all_issues:
        issues = [i for i in issues if i["status"] in _ACTIVE_STATUSES]

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
                issue["assignee"],
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
            "Claimed By",
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


def render_beads_board(client: LuxClient) -> None:
    """Send the beads issue board to the display via *client*.

    Looks for ``.beads/`` in the current working directory.  If not found
    or empty, renders a placeholder message.  Uses ``show_async`` so the
    call is non-blocking (safe to call from a menu callback thread).
    """
    beads_dir = Path(".beads")
    project = Path.cwd().name or "unknown"
    frame_id = f"beads-{project}"

    if not beads_dir.is_dir():
        client.show_async(
            f"beads-{project}",
            elements=[
                TextElement(
                    id="no-beads",
                    content=(
                        "No .beads/ directory found.\nRun `bd init` to set up beads."
                    ),
                ),
            ],
            frame_id=frame_id,
            frame_title=f"Beads: {project}",
        )
        return

    try:
        issues = load_beads(beads_dir)
    except ValueError as exc:
        client.show_async(
            f"beads-{project}",
            elements=[
                TextElement(id="error", content=f"Error loading beads:\n{exc}"),
            ],
            frame_id=frame_id,
            frame_title=f"Beads: {project}",
        )
        return

    if not issues:
        client.show_async(
            f"beads-{project}",
            elements=[
                TextElement(id="empty", content="No active issues."),
            ],
            frame_id=frame_id,
            frame_title=f"Beads: {project}",
        )
        return

    payload = build_beads_payload(issues)

    table = element_from_dict(
        {
            "kind": "table",
            "id": "table",
            "columns": payload["columns"],
            "rows": payload["rows"],
            "flags": ["borders", "row_bg", "resizable", "copy_id"],
            "filters": payload["filters"],
            "detail": payload["detail"],
        }
    )

    client.show_async(
        f"beads-{project}",
        elements=[table],
        frame_id=frame_id,
        frame_title=f"Beads: {project}",
    )
