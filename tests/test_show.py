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
from punt_lux.protocol import TextElement

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
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(active),
        ):
            result, _err = BeadsBrowser().load()
        assert len(result) == 2
        assert all(i["status"] in {"open", "in_progress"} for i in result)

    def test_all_flag_includes_closed(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ):
            result, _err = BeadsBrowser().load(all_issues=True)
        assert len(result) == 3

    def test_sorted_in_progress_first_then_priority(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ):
            result, _err = BeadsBrowser().load(all_issues=True)
        assert result[0]["id"] == "beads-002"  # in_progress floats to top
        assert result[1]["id"] == "beads-001"  # P1, open

    def test_subprocess_failure_returns_empty(self) -> None:
        cp = subprocess.CompletedProcess(
            args=["bd", "list", "--json"],
            returncode=1,
            stdout="",
            stderr="db locked",
        )
        with patch("punt_lux.apps._beads_payload.subprocess.run", return_value=cp):
            issues, err = BeadsBrowser().load()
        assert issues == []
        assert err is not None
        assert "db locked" in err

    def test_defaults_applied(self) -> None:
        minimal = [{"id": "beads-100"}]
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(minimal),
        ):
            result, _err = BeadsBrowser().load()
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
        with patch("punt_lux.apps._beads_payload.subprocess.run", return_value=cp):
            issues, err = BeadsBrowser().load()
        assert issues == []
        assert err is not None
        assert "no output" in err

    def test_invalid_json_returns_empty(self) -> None:
        cp = subprocess.CompletedProcess(
            args=["bd", "list", "--json"],
            returncode=0,
            stdout="not-json",
            stderr="",
        )
        with patch("punt_lux.apps._beads_payload.subprocess.run", return_value=cp):
            issues, err = BeadsBrowser().load()
        assert issues == []
        assert err is not None
        assert "JSON" in err or "malformed" in err

    def test_unexpected_json_shape_returns_error(self) -> None:
        cp = subprocess.CompletedProcess(
            args=["bd", "ready", "--json"],
            returncode=0,
            stdout=json.dumps({"issues": _ISSUES}),
            stderr="",
        )
        with patch("punt_lux.apps._beads_payload.subprocess.run", return_value=cp):
            issues, err = BeadsBrowser().load()
        assert issues == []
        assert err is not None
        assert "unexpected JSON shape" in err

    def test_subprocess_timeout_returns_error(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="bd ready --json", timeout=60),
        ):
            issues, err = BeadsBrowser().load()
        assert issues == []
        assert err is not None
        assert "timed out" in err

    def test_passes_all_flag_to_bd(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load(all_issues=True)
        args = mock_run.call_args[0][0]
        assert "--all" in args

    def test_default_invokes_bd_ready(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load()
        args = mock_run.call_args[0][0]
        assert args == ["bd", "ready", "--json"]

    def test_all_flag_invokes_bd_list_all(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load(all_issues=True)
        args = mock_run.call_args[0][0]
        assert args == ["bd", "list", "--json", "--all"]

    def test_subprocess_timeout_is_60_seconds(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load()
        assert mock_run.call_args.kwargs["timeout"] == 60

    def test_bd_not_found_returns_empty(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            side_effect=FileNotFoundError("bd not found"),
        ):
            issues, err = BeadsBrowser().load()
        assert issues == []
        assert err is not None
        assert "not found" in err.lower() or "no such file" in err.lower()


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
        elements = BeadsBrowser().build_elements(([], None))
        assert len(elements) == 1
        assert elements[0].kind == "text"
        assert "No active issues" in elements[0].content

    def test_nonempty_issues_returns_table(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        elements = BeadsBrowser().build_elements((active, None))
        assert len(elements) == 1
        assert elements[0].kind == "table"
        assert elements[0].id == "table"
        assert len(elements[0].rows) == 2
        assert elements[0].columns == ["ID", "Title", "Status", "P", "Type"]

    def test_error_returns_visible_error_element(self) -> None:
        """When bd fails, surface the reason instead of 'No active issues'."""
        elements = BeadsBrowser().build_elements(
            ([], "bd ready --json: timed out after 60s"),
        )
        assert len(elements) == 1
        elem = elements[0]
        assert isinstance(elem, TextElement)
        assert elem.id == "bd-error"
        assert "bd unavailable" in elem.content
        assert "timed out" in elem.content
        # Error element distinguishes itself visually (non-None color).
        assert elem.color is not None

    def test_error_overrides_empty_placeholder(self) -> None:
        """Empty issues + error renders the error, not the empty placeholder."""
        elements = BeadsBrowser().build_elements(([], "connection refused"))
        elem = elements[0]
        assert isinstance(elem, TextElement)
        assert elem.id == "bd-error"
        assert "No active issues" not in elem.content


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestShowBeadsCLI:
    def test_bd_failure_surfaces_error(
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
                "punt_lux.apps._beads_payload.subprocess.run",
                return_value=_mock_bd_result([], returncode=1),
            ),
            patch("punt_lux.display_client.DisplayClient", return_value=mock_client),
        ):
            result = runner.invoke(
                app,
                ["show", "beads", "--socket", sock],
            )

        # When bd fails, the CLI reports the error rather than misleading "0 issues".
        # The display still receives a frame with a visible error element.
        assert result.exit_code == 0
        assert "bd error" in result.output
        # Verify the scene has the error element, not "No active issues".
        sent_elements = (
            mock_client.show.call_args.kwargs.get("elements")
            or mock_client.show.call_args.args[1]
        )
        ids = [getattr(e, "id", None) for e in sent_elements]
        assert "bd-error" in ids, f"expected bd-error element, got: {ids}"

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
                "punt_lux.apps._beads_payload.subprocess.run",
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
                "punt_lux.apps._beads_payload.subprocess.run",
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
