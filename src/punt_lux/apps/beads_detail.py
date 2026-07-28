"""Compose a beads issue's detail-pane markdown."""

from __future__ import annotations

from typing import Any, final


@final
class BeadsDetail:
    """Render beads issues as detail-pane markdown: a fields table, a rule, a body.

    The metadata is a compact two-column table — every value is an id, enum, date,
    or handle, never prose, so it is safe from the U+2192-in-a-cell tofu of
    lux-efun. The description follows a horizontal rule as its own paragraphs,
    presented as written rather than restructured, so the fields block and the
    description read as distinct regions instead of one inline run.
    """

    __slots__ = ()

    @classmethod
    def for_issues(cls, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Return the table-composition ``detail`` dict for a list of issues.

        ``fields`` and ``rows`` are left empty: the composed markdown is the whole
        detail body, so the generic field/value rendering adds nothing to run
        inline with it. ``body`` is parallel to the table's rows.
        """
        return {"fields": [], "rows": [], "body": [cls._markdown(i) for i in issues]}

    @staticmethod
    def _markdown(issue: dict[str, Any]) -> str:
        """Return one issue's detail markdown: metadata table, rule, description."""
        fields = (
            ("ID", issue.get("id", "")),
            ("Status", issue["status"]),
            ("Priority", f"P{issue['priority']}"),
            ("Type", issue["issue_type"]),
            ("Owner", issue["owner"] or "unassigned"),
            ("Created", issue["created_at"][:10]),
            ("Updated", issue["updated_at"][:10]),
        )
        rows = "\n".join(f"| {label} | {value} |" for label, value in fields)
        table = f"| Field | Value |\n| --- | --- |\n{rows}"
        description = issue["description"] or "_No description._"
        return f"{table}\n\n---\n\n{description}"
