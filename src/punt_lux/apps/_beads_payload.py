"""Beads loader and payload builder — subprocess, parsing, and table assembly."""

from __future__ import annotations

import json
import logging
import subprocess
from enum import Enum
from typing import Any, ClassVar, cast

_log = logging.getLogger(__name__)
_STDOUT_PREVIEW_CHARS = 80
_BD_TIMEOUT_SECONDS = 60


class BoardScope(Enum):
    """Which beads the board shows — the query scope the loader owns.

    Each member carries the ``bd`` argument tail that selects its issues;
    ``ACTIVE`` is the board's default and shows ready work *plus* whatever is
    currently in progress, so a claimed bead stays visible instead of dropping
    off the moment its status flips to ``in_progress``. ``ALL`` shows every
    issue regardless of status.
    """

    ACTIVE = ("list", "--json", "--status", "open,in_progress")
    ALL = ("list", "--json", "--all")

    @classmethod
    def for_board(cls, *, all_issues: bool) -> BoardScope:
        """Return the scope a board load asks for."""
        return cls.ALL if all_issues else cls.ACTIVE

    def argv(self) -> list[str]:
        """Return the full ``bd`` command line that selects this scope."""
        return ["bd", *self.value]


class BeadsLoader:
    """Invoke ``bd`` and parse its JSON output into issue dicts."""

    def run(self, *, all_issues: bool) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch and parse beads issues. Return ``(issues, error)``.

        ``error`` is ``None`` on success and a short reason string on
        failure (timeout, non-zero exit, empty output, malformed JSON,
        or an unexpected JSON shape).
        """
        stdout, err = self._invoke(BoardScope.for_board(all_issues=all_issues))
        if stdout is None:
            return [], err
        return self._parse(stdout)

    def _invoke(self, scope: BoardScope) -> tuple[str | None, str | None]:
        cmd = scope.argv()
        cmd_str = " ".join(cmd)
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=_BD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return None, f"{cmd_str}: timed out after {_BD_TIMEOUT_SECONDS}s"
        except OSError as exc:
            return None, f"{cmd_str}: {exc}"
        if result.returncode != 0:
            err = result.stderr.strip()[:200] or f"exit {result.returncode}"
            return None, f"{cmd_str}: {err}"
        if not result.stdout.strip():
            return None, f"{cmd_str}: no output"
        return result.stdout, None

    def _parse(self, stdout: str) -> tuple[list[dict[str, Any]], str | None]:
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError as exc:
            preview = stdout.strip()[:_STDOUT_PREVIEW_CHARS]
            return [], f"malformed JSON from bd ({exc.msg}): {preview!r}"
        if not isinstance(raw, list):
            kind = type(raw).__name__
            return [], f"unexpected JSON shape: top-level is {kind}, expected list"

        builder = BeadsPayloadBuilder()
        issues: list[dict[str, Any]] = []
        skipped = 0
        for entry in cast("list[Any]", raw):  # type: ignore[redundant-cast]
            if not isinstance(entry, dict):
                skipped += 1
                continue
            issues.append(builder.apply_defaults(cast("dict[str, Any]", entry)))
        if skipped:
            _log.warning("dropped %d non-dict entries from bd output", skipped)
        return issues, None


class BeadsPayloadBuilder:
    """Assemble show_table payloads and per-issue defaults for beads issues."""

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

    def apply_defaults(self, row: dict[str, Any]) -> dict[str, Any]:
        """Fill missing fields with FIELD_DEFAULTS; return the same row."""
        for key, default in self.FIELD_DEFAULTS.items():
            if row.get(key) is None:
                row[key] = default
        return row

    def build(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the show_table element dict and metadata for beads issues."""
        rows = [self._row(i) for i in issues]
        detail_rows = [self._detail_row(i) for i in issues]
        detail_bodies = [i["description"] or "No description." for i in issues]
        statuses = sorted({i["status"] for i in issues})
        types = sorted({i["issue_type"] for i in issues})

        return {
            "columns": ["ID", "Title", "Status", "P", "Type"],
            "rows": rows,
            "filters": [
                {
                    "type": "search",
                    "column": [0, 1],
                    "hint": "Filter by ID or title...",
                },
                {
                    "type": "combo",
                    "column": 2,
                    "items": ["All", *statuses],
                    "label": "Status",
                },
                {
                    "type": "combo",
                    "column": 4,
                    "items": ["All", *types],
                    "label": "Type",
                },
            ],
            "detail": {
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
            },
        }

    @staticmethod
    def _row(issue: dict[str, Any]) -> list[Any]:
        return [
            issue.get("id", ""),
            issue["title"],
            issue["status"],
            f"P{issue['priority']}",
            issue["issue_type"],
        ]

    @staticmethod
    def _detail_row(issue: dict[str, Any]) -> list[str]:
        return [
            issue.get("id", ""),
            issue["status"],
            f"P{issue['priority']}",
            issue["issue_type"],
            issue["owner"],
            issue["created_at"][:10],
            issue["updated_at"][:10],
        ]
