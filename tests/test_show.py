"""Unit tests for ``lux show`` subcommands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from punt_lux.__main__ import app
from punt_lux.show import build_beads_payload, load_beads

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ISSUES = [
    {
        "id": "beads-001",
        "title": "Fix login bug",
        "status": "open",
        "priority": 1,
        "issue_type": "bug",
        "description": "Login fails on slow networks.",
        "assignee": "alice",
        "owner": "bob",
        "created_at": "2026-03-01T00:00:00Z",
        "updated_at": "2026-03-09T12:00:00Z",
    },
    {
        "id": "beads-002",
        "title": "Add dark mode",
        "status": "in_progress",
        "priority": 2,
        "issue_type": "feature",
        "description": "",
        "assignee": "",
        "owner": "",
        "created_at": "2026-03-02T00:00:00Z",
        "updated_at": "2026-03-08T10:00:00Z",
    },
    {
        "id": "beads-003",
        "title": "Old task",
        "status": "closed",
        "priority": 3,
        "issue_type": "task",
        "description": "Done.",
        "assignee": "",
        "owner": "",
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-15T00:00:00Z",
    },
]


def _write_issues(beads_dir: Path, issues: list[dict[str, Any]]) -> None:
    beads_dir.mkdir(parents=True, exist_ok=True)
    path = beads_dir / "issues.jsonl"
    path.write_text("\n".join(json.dumps(i) for i in issues) + "\n")


# ---------------------------------------------------------------------------
# load_beads
# ---------------------------------------------------------------------------


class TestLoadBeads:
    def test_filters_closed_by_default(self, tmp_path: Path) -> None:
        _write_issues(tmp_path, _ISSUES)
        result = load_beads(tmp_path)
        assert len(result) == 2
        assert all(i["status"] in {"open", "in_progress"} for i in result)

    def test_all_flag_includes_closed(self, tmp_path: Path) -> None:
        _write_issues(tmp_path, _ISSUES)
        result = load_beads(tmp_path, all_issues=True)
        assert len(result) == 3

    def test_sorted_by_priority_then_updated(self, tmp_path: Path) -> None:
        _write_issues(tmp_path, _ISSUES)
        result = load_beads(tmp_path)
        assert result[0]["id"] == "beads-001"  # P1
        assert result[1]["id"] == "beads-002"  # P2

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_beads(tmp_path) == []

    def test_defaults_applied(self, tmp_path: Path) -> None:
        minimal = [{"id": "beads-100"}]
        _write_issues(tmp_path, minimal)
        result = load_beads(tmp_path)
        assert result[0]["status"] == "open"
        assert result[0]["priority"] == 4
        assert result[0]["issue_type"] == "task"

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        beads_dir = tmp_path
        beads_dir.mkdir(parents=True, exist_ok=True)
        path = beads_dir / "issues.jsonl"
        lines = json.dumps(_ISSUES[0]) + "\n\n\n"
        lines += json.dumps(_ISSUES[1]) + "\n"
        path.write_text(lines)
        result = load_beads(beads_dir)
        assert len(result) == 2

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        path = beads_dir / "issues.jsonl"
        path.write_text('{"id": "ok"}\nnot-json\n')
        with __import__("pytest").raises(ValueError, match="Malformed JSON"):
            load_beads(beads_dir)

    def test_non_dict_json_raises(self, tmp_path: Path) -> None:
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        path = beads_dir / "issues.jsonl"
        path.write_text("[1, 2, 3]\n")
        with __import__("pytest").raises(ValueError, match="Expected JSON"):
            load_beads(beads_dir)


# ---------------------------------------------------------------------------
# build_beads_payload
# ---------------------------------------------------------------------------


class TestBuildBeadsPayload:
    def test_columns(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = build_beads_payload(active)
        assert payload["columns"] == ["ID", "Title", "Status", "P", "Type"]

    def test_rows_match_issues(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = build_beads_payload(active)
        assert len(payload["rows"]) == 2
        assert payload["rows"][0][0] == "beads-001"
        assert payload["rows"][0][3] == "P1"

    def test_detail_truncates_dates(self) -> None:
        active = [_ISSUES[0]]
        payload = build_beads_payload(active)
        detail_row = payload["detail"]["rows"][0]
        assert detail_row[6] == "2026-03-01"  # created_at truncated
        assert detail_row[7] == "2026-03-09"  # updated_at truncated

    def test_empty_description_shows_placeholder(self) -> None:
        active = [_ISSUES[1]]  # description is ""
        payload = build_beads_payload(active)
        assert payload["detail"]["body"][0] == "No description."

    def test_filters_include_unique_values(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = build_beads_payload(active)
        status_filter = payload["filters"][1]
        assert status_filter["items"][0] == "All"
        assert "in_progress" in status_filter["items"]
        assert "open" in status_filter["items"]

    def test_empty_issues(self) -> None:
        payload = build_beads_payload([])
        assert payload["rows"] == []
        assert payload["detail"]["rows"] == []


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestShowBeadsCLI:
    def test_no_beads_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["show", "beads"])
        assert result.exit_code == 1
        assert ".beads/" in result.output

    def test_show_beads_sends_to_display(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _write_issues(tmp_path / ".beads", _ISSUES)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.show = MagicMock(return_value=MagicMock(scene_id="beads-test"))

        sock = str(tmp_path / "test.sock")
        with patch("punt_lux.client.LuxClient", return_value=mock_client):
            result = runner.invoke(
                app,
                ["show", "beads", "--socket", sock],
            )

        assert result.exit_code == 0
        assert "2 issues" in result.output
        mock_client.show.assert_called_once()
        call_args = mock_client.show.call_args
        scene_id = call_args[0][0]
        assert scene_id.startswith("beads-")  # project-scoped tab

    def test_show_beads_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _write_issues(tmp_path / ".beads", _ISSUES)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.show = MagicMock(return_value=None)

        sock = str(tmp_path / "test.sock")
        with patch("punt_lux.client.LuxClient", return_value=mock_client):
            result = runner.invoke(
                app,
                ["show", "beads", "--socket", sock],
            )

        assert result.exit_code == 1
        assert "Timeout" in result.output

    def test_show_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["show"])
        assert result.exit_code in {0, 2}
        assert "beads" in result.output.lower()
