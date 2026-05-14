"""Unit tests for ``lux show`` subcommands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from punt_lux.__main__ import app
from punt_lux.apps.beads import BeadsBrowser

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
        "owner": "",
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-15T00:00:00Z",
    },
]


def _mock_bd_result(
    issues: list[dict[str, Any]],
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Build a ``CompletedProcess`` mimicking ``bd list --json`` output."""
    return subprocess.CompletedProcess(
        args=["bd", "list", "--json"],
        returncode=returncode,
        stdout=json.dumps(issues) if returncode == 0 else "",
        stderr="",
    )


# ---------------------------------------------------------------------------
# load_beads
# ---------------------------------------------------------------------------


class TestLoadBeads:
    def test_filters_closed_by_default(self) -> None:
        # bd does the filtering server-side; mock returns only active issues
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            return_value=_mock_bd_result(active),
        ):
            result = BeadsBrowser().load()
        assert len(result) == 2
        assert all(i["status"] in {"open", "in_progress"} for i in result)

    def test_all_flag_includes_closed(self) -> None:
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ):
            result = BeadsBrowser().load(all_issues=True)
        assert len(result) == 3

    def test_sorted_in_progress_first_then_priority(self) -> None:
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ):
            result = BeadsBrowser().load(all_issues=True)
        assert result[0]["id"] == "beads-002"  # in_progress floats to top
        assert result[1]["id"] == "beads-001"  # P1, open

    def test_subprocess_failure_returns_empty(self) -> None:
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            return_value=_mock_bd_result([], returncode=1),
        ):
            assert BeadsBrowser().load() == []

    def test_defaults_applied(self) -> None:
        minimal = [{"id": "beads-100"}]
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            return_value=_mock_bd_result(minimal),
        ):
            result = BeadsBrowser().load()
        assert result[0]["status"] == "open"
        assert result[0]["priority"] == 4
        assert result[0]["issue_type"] == "task"

    def test_empty_stdout_returns_empty(self) -> None:
        cp = subprocess.CompletedProcess(
            args=["bd", "list", "--json"],
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch("punt_lux.apps.beads.subprocess.run", return_value=cp):
            assert BeadsBrowser().load() == []

    def test_invalid_json_returns_empty(self) -> None:
        cp = subprocess.CompletedProcess(
            args=["bd", "list", "--json"],
            returncode=0,
            stdout="not-json",
            stderr="",
        )
        with patch("punt_lux.apps.beads.subprocess.run", return_value=cp):
            assert BeadsBrowser().load() == []

    def test_passes_all_flag_to_bd(self) -> None:
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load(all_issues=True)
        args = mock_run.call_args[0][0]
        assert "--all" in args

    def test_passes_status_filter_by_default(self) -> None:
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load()
        args = mock_run.call_args[0][0]
        assert "--status=open,in_progress" in args

    def test_bd_not_found_returns_empty(self) -> None:
        with patch(
            "punt_lux.apps.beads.subprocess.run",
            side_effect=FileNotFoundError("bd not found"),
        ):
            assert BeadsBrowser().load() == []


# ---------------------------------------------------------------------------
# build_beads_payload
# ---------------------------------------------------------------------------


class TestBuildBeadsPayload:
    def test_columns(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = BeadsBrowser().build_payload(active)
        assert payload["columns"] == ["ID", "Title", "Status", "P", "Type"]

    def test_rows_match_issues(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = BeadsBrowser().build_payload(active)
        assert len(payload["rows"]) == 2
        assert payload["rows"][0][0] == "beads-001"
        assert payload["rows"][0][3] == "P1"

    def test_detail_truncates_dates(self) -> None:
        active = [_ISSUES[0]]
        payload = BeadsBrowser().build_payload(active)
        detail_row = payload["detail"]["rows"][0]
        assert detail_row[5] == "2026-03-01"  # created_at truncated
        assert detail_row[6] == "2026-03-09"  # updated_at truncated

    def test_empty_description_shows_placeholder(self) -> None:
        active = [_ISSUES[1]]  # description is ""
        payload = BeadsBrowser().build_payload(active)
        assert payload["detail"]["body"][0] == "No description."

    def test_filters_include_unique_values(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = BeadsBrowser().build_payload(active)
        status_filter = payload["filters"][1]
        assert status_filter["items"][0] == "All"
        assert "in_progress" in status_filter["items"]
        assert "open" in status_filter["items"]

    def test_empty_issues(self) -> None:
        payload = BeadsBrowser().build_payload([])
        assert payload["rows"] == []
        assert payload["detail"]["rows"] == []


# ---------------------------------------------------------------------------
# build_beads_elements
# ---------------------------------------------------------------------------


class TestBuildBeadsElements:
    def test_empty_issues_returns_placeholder(self) -> None:
        elements = BeadsBrowser().build_elements([])
        assert len(elements) == 1
        assert elements[0].kind == "text"
        assert "No active issues" in elements[0].content

    def test_nonempty_issues_returns_table(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        elements = BeadsBrowser().build_elements(active)
        assert len(elements) == 1
        assert elements[0].kind == "table"
        assert elements[0].id == "table"
        assert len(elements[0].rows) == 2
        assert elements[0].columns == ["ID", "Title", "Status", "P", "Type"]


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestShowBeadsCLI:
    def test_bd_failure_shows_empty_board(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.show = MagicMock(return_value=MagicMock(scene_id="beads-test"))

        sock = str(tmp_path / "test.sock")
        with (
            patch(
                "punt_lux.apps.beads.subprocess.run",
                return_value=_mock_bd_result([], returncode=1),
            ),
            patch("punt_lux.display_client.DisplayClient", return_value=mock_client),
        ):
            result = runner.invoke(
                app,
                ["show", "beads", "--socket", sock],
            )

        assert result.exit_code == 0
        assert "0 issues" in result.output

    def test_show_beads_sends_to_display(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.show = MagicMock(return_value=MagicMock(scene_id="beads-test"))

        # bd does server-side filtering; mock returns only active issues
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        sock = str(tmp_path / "test.sock")
        with (
            patch(
                "punt_lux.apps.beads.subprocess.run",
                return_value=_mock_bd_result(active),
            ),
            patch("punt_lux.display_client.DisplayClient", return_value=mock_client),
        ):
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

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.show = MagicMock(return_value=None)

        sock = str(tmp_path / "test.sock")
        with (
            patch(
                "punt_lux.apps.beads.subprocess.run",
                return_value=_mock_bd_result(_ISSUES),
            ),
            patch("punt_lux.display_client.DisplayClient", return_value=mock_client),
        ):
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
