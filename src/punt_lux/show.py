"""CLI subcommands for ``lux show`` — pre-built display scenes.

Each command reads local data, builds a scene payload, and sends it
to the display server via :class:`LuxClient`.  No MCP round-trip,
no LLM in the loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import typer

show_app = typer.Typer(
    help="Show pre-built scenes in the Lux display.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Beads helpers (pure, testable)
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

    Returns issues sorted by priority ascending, then updated_at descending.
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
            row.setdefault(key, default)
        issues.append(row)

    if not all_issues:
        issues = [i for i in issues if i["status"] in _ACTIVE_STATUSES]

    # Two-pass stable sort: updated_at desc first, then priority asc.
    # Python's stable sort preserves updated_at order within equal priorities.
    issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
    issues.sort(key=lambda i: i["priority"])

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
# CLI command
# ---------------------------------------------------------------------------


@show_app.command("beads")
def beads(
    socket: str | None = typer.Option(None, "--socket", "-s", help="Socket path"),
    all_issues: bool = typer.Option(False, "--all", "-a", help="Include closed issues"),
) -> None:
    """Display the beads issue board in the Lux window."""
    from punt_lux.client import LuxClient
    from punt_lux.paths import default_socket_path
    from punt_lux.protocol import element_from_dict

    beads_dir = Path(".beads")
    if not beads_dir.is_dir():
        typer.echo(
            "No .beads/ directory found. Run `bd init` to set up beads.",
            err=True,
        )
        raise typer.Exit(code=1)

    issues = load_beads(beads_dir, all_issues=all_issues)
    if not issues:
        typer.echo("No issues to display.")
        raise typer.Exit(code=0)

    payload = build_beads_payload(issues)

    table: dict[str, Any] = {
        "kind": "table",
        "id": "table",
        "columns": payload["columns"],
        "rows": payload["rows"],
        "flags": ["borders", "row_bg", "copy_id"],
        "filters": payload["filters"],
        "detail": payload["detail"],
    }

    sock_path = Path(socket) if socket else default_socket_path()
    elements = [element_from_dict(table)]

    with LuxClient(sock_path) as client:
        ack = client.show("beads-board", elements, title="Beads")

    if ack is None:
        typer.echo("Timeout: display server did not respond.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Beads board displayed ({len(issues)} issues).")
