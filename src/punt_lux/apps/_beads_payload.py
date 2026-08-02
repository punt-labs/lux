"""Beads loader and payload builder — parsing and table assembly."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, ClassVar, cast

from punt_lux.apps.bd_command import BdOutput, BdRun, BoardScope
from punt_lux.apps.beads_detail import BeadsDetail
from punt_lux.apps.beads_load import BeadsLoad
from punt_lux.apps.beads_result import BeadsFailure, BeadsResult, BeadsRows

_log = logging.getLogger(__name__)
_STDOUT_PREVIEW_CHARS = 80


class BeadsLoader:
    """Invoke ``bd`` and parse its JSON output into issue dicts."""

    def run(self, *, all_issues: bool) -> BeadsLoad:
        """Fetch and parse beads issues, with where the run's time went.

        A failure — timeout, non-zero exit, empty output, malformed JSON, or an
        unexpected JSON shape — comes back as the reason to show, never as an
        empty board, so the caller can tell "nothing open" from "bd did not run".

        The parse is timed here rather than inside ``bd``'s figure because it is
        lux's own work: turning a pipe full of JSON into rows is a cost the
        board pays, and one a large backlog can make visible.
        """
        output = BdRun().completed(BoardScope.for_board(all_issues=all_issues))
        if isinstance(output, BeadsFailure):
            return BeadsLoad.failed(output)
        return self._parsed(output)

    def _parsed(self, output: BdOutput) -> BeadsLoad:
        """Turn what ``bd`` wrote into rows, timing that work as its own figure."""
        began = time.perf_counter()
        result = self._parse(output.text)
        return BeadsLoad(result, output, (time.perf_counter() - began) * 1000.0)

    def _parse(self, stdout: str) -> BeadsResult:
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError as exc:
            preview = stdout.strip()[:_STDOUT_PREVIEW_CHARS]
            return BeadsFailure(f"malformed JSON from bd ({exc.msg}): {preview!r}")
        if not isinstance(raw, list):
            kind = type(raw).__name__
            return BeadsFailure(
                f"unexpected JSON shape: top-level is {kind}, expected list"
            )

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
        return BeadsRows.of(issues)


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
        """Build the show_table element dict and metadata for beads issues.

        ``BeadsDetail`` composes each issue's detail markdown — a metadata table,
        a rule, then the description — so the fields and the prose read as
        distinct regions rather than as one inline run.
        """
        return {
            "columns": self._columns(),
            "rows": [self._row(i) for i in issues],
            "filters": self._filters(issues),
            "detail": BeadsDetail.for_issues(issues),
        }

    @staticmethod
    def _columns() -> list[str]:
        """The board's columns, in the order the table shows them."""
        return ["ID", "Title", "Status", "P", "Type"]

    def _filters(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The board's chrome: a search over id and title, and a combo per facet.

        A combo offers only the values actually present, plus ``All``, so a board
        with nothing in progress does not offer to filter for it.
        """
        statuses = sorted({i["status"] for i in issues})
        types = sorted({i["issue_type"] for i in issues})
        return [
            {"type": "search", "column": [0, 1], "hint": "Filter by ID or title..."},
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
        ]

    @staticmethod
    def _row(issue: dict[str, Any]) -> list[Any]:
        return [
            issue.get("id", ""),
            issue["title"],
            issue["status"],
            f"P{issue['priority']}",
            issue["issue_type"],
        ]
