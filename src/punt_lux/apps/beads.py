"""Beads Browser — display beads issues in a Lux frame."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from punt_lux.protocol import Element, TextElement, element_from_dict

if TYPE_CHECKING:
    from punt_lux.display_client import DisplayClient


class BeadsBrowser:
    """Fetch, format, and render beads issues as a Lux table."""

    FIELD_DEFAULTS: ClassVar[dict[str, Any]] = {
        "title": "",
        "status": "open",
        "priority": 4,
        "issue_type": "task",
        "description": "",
        "owner": "",
        "created_at": "",
        "updated_at": "",
    }

    def load(self, *, all_issues: bool = False) -> list[dict[str, Any]]:
        """Fetch, default-fill, filter, and sort beads issues via ``bd list --json``."""
        stdout = self._run_bd(all_issues=all_issues)
        if stdout is None:
            return []

        issues = self._parse_issues(stdout)

        # Three-pass stable sort: updated_at desc, then priority asc, then
        # in_progress floats to top.
        issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        issues.sort(key=lambda i: i["priority"])
        issues.sort(key=lambda i: i["status"] != "in_progress")

        return issues

    def _run_bd(self, *, all_issues: bool) -> str | None:
        """Invoke ``bd list --json`` and return stdout, or None on failure."""
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
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return result.stdout

    def _parse_issues(self, stdout: str) -> list[dict[str, Any]]:
        """Parse JSON output and apply field defaults."""
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        if not isinstance(raw, list):
            return []
        issues: list[dict[str, Any]] = []
        for entry in cast("list[Any]", raw):  # type: ignore[redundant-cast]
            if not isinstance(entry, dict):
                continue
            row = cast("dict[str, Any]", entry)
            for key, default in self.FIELD_DEFAULTS.items():
                if row.get(key) is None:
                    row[key] = default
            issues.append(row)
        return issues

    def build_payload(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the show_table element dict and metadata for beads issues."""
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

    def build_elements(self, issues: list[dict[str, Any]]) -> list[Element]:
        """Build display elements for a beads issue list."""
        if not issues:
            return [TextElement(id="empty", content="No active issues.")]

        payload = self.build_payload(issues)
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

    def render(self, client: DisplayClient) -> None:
        """Send the beads issue board to the display via *client*."""
        project = Path.cwd().name or "unknown"
        frame_id = f"beads-{project}"

        issues = self.load()

        client.show_async(
            f"beads-{project}",
            elements=self.build_elements(issues),
            frame_id=frame_id,
            frame_title=f"Beads: {project}",
        )
