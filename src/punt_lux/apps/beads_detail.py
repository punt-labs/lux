"""Compose a beads issue's detail-pane markdown."""

from __future__ import annotations

from typing import Any, final


@final
class BeadsDetail:
    """Render beads issues as detail-pane markdown: a fields table, a rule, a body.

    Cell values are pipe-escaped and carry no U+2192, so the metadata table is
    safe from lux-efun tofu. The description follows a rule as its own paragraphs,
    presented as written, so the fields and description read as distinct regions.
    """

    __slots__ = ()

    @classmethod
    def for_issues(cls, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Return the ``detail`` dict; ``body`` carries the composed markdown.

        ``fields`` and ``rows`` are left empty so the generic field/value
        rendering adds nothing to run inline; ``body`` is parallel to the rows.
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
        rows = "\n".join(
            f"| {label} | {str(value).replace('|', r'\|')} |" for label, value in fields
        )
        table = f"| Field | Value |\n| --- | --- |\n{rows}"
        description = issue["description"] or "_No description._"
        return f"{table}\n\n---\n\n{description}"
