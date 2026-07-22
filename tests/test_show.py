"""Unit tests for ``lux show`` subcommands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from punt_lux.__main__ import app
from punt_lux.apps.beads import BeadsBrowser
from punt_lux.operations import OpError, RenderRequest, SceneShown
from punt_lux.operations.models.render import FrameSpec
from punt_lux.protocol import TextElement
from punt_lux.rest_transport import HubUnavailableError
from punt_lux.show import BeadsBoard

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

    def test_default_floats_in_progress_above_open(self) -> None:
        # The default board query returns open + in_progress issues; the
        # in_progress bead must float to the top even though its priority is
        # lower than an open bead's, exercising the default-path sort.
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(active),
        ):
            result, _err = BeadsBrowser().load()
        assert [i["id"] for i in result] == ["beads-002", "beads-001"]
        assert result[0]["status"] == "in_progress"
        assert result[1]["priority"] < result[0]["priority"]  # P1 open below P2

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
            args=["bd", "list", "--json", "--status", "open,in_progress"],
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
            side_effect=subprocess.TimeoutExpired(
                cmd="bd list --json --status open,in_progress", timeout=60
            ),
        ):
            issues, err = BeadsBrowser().load()
        assert issues == []
        assert err is not None
        assert "timed out" in err

    def test_non_dict_entries_dropped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cp = subprocess.CompletedProcess(
            args=["bd", "list", "--json", "--status", "open,in_progress"],
            returncode=0,
            stdout=json.dumps([{"id": "beads-001", "title": "ok"}, "garbage", 42]),
            stderr="",
        )
        with (
            caplog.at_level("WARNING", logger="punt_lux.apps._beads_payload"),
            patch("punt_lux.apps._beads_payload.subprocess.run", return_value=cp),
        ):
            issues, err = BeadsBrowser().load()
        assert err is None
        assert len(issues) == 1
        assert "dropped 2 non-dict entries" in caplog.text

    def test_passes_all_flag_to_bd(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load(all_issues=True)
        args = mock_run.call_args[0][0]
        assert "--all" in args

    def test_default_invokes_bd_list_active(self) -> None:
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(_ISSUES),
        ) as mock_run:
            BeadsBrowser().load()
        args = mock_run.call_args[0][0]
        assert args == ["bd", "list", "--json", "--status", "open,in_progress"]

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
            ([], "bd list --json --status open,in_progress: timed out after 60s"),
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


class _RecordingClient:
    """A LuxRestClient stand-in that records the request and reports success."""

    def __init__(self) -> None:
        self.request: RenderRequest | None = None

    def render(self, request: RenderRequest) -> SceneShown:
        self.request = request
        return SceneShown(scene_id=request.scene_id)


class _RejectingClient:
    """A LuxRestClient stand-in whose render is refused by the Hub."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def render(self, request: RenderRequest) -> OpError:
        return OpError(code="rejected", reason=self._reason)


class _UnreachableClient:
    """A LuxRestClient stand-in whose render finds luxd gone mid-call.

    ``connect`` only reads the port file; the socket work happens in ``render``,
    so an unreachable luxd raises there, not at connect time.
    """

    def render(self, request: RenderRequest) -> SceneShown:
        raise HubUnavailableError("luxd is not reachable on port 5001 — refused")


class TestBeadsBoard:
    def test_request_carries_the_frame_envelope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The render envelope must name the scene, title, and frame after the
        # project directory, so the board lands in its own project-scoped tab.
        monkeypatch.chdir(tmp_path)
        project = tmp_path.name
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with patch(
            "punt_lux.apps._beads_payload.subprocess.run",
            return_value=_mock_bd_result(active),
        ):
            request, note = BeadsBoard().request(all_issues=False)
        assert request.scene_id == f"beads-{project}"
        assert request.title == f"Beads: {project}"
        assert request.frame == FrameSpec(
            frame_id=f"beads-{project}", frame_title=f"Beads: {project}"
        )
        assert note == "2 issues"


class TestShowBeadsCLI:
    def test_bd_failure_surfaces_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        client = _RecordingClient()
        with (
            patch(
                "punt_lux.apps._beads_payload.subprocess.run",
                return_value=_mock_bd_result([], returncode=1),
            ),
            patch("punt_lux.show.LuxRestClient.connect", return_value=client),
        ):
            result = runner.invoke(app, ["show", "beads"])

        # When bd fails, the CLI reports the error rather than misleading "0 issues".
        # luxd still receives a scene carrying a visible error element.
        assert result.exit_code == 0
        assert "bd error" in result.output
        assert client.request is not None
        ids = [e.get("id") for e in client.request.elements]
        assert "bd-error" in ids, f"expected bd-error element, got: {ids}"

    def test_show_beads_sends_to_luxd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        client = _RecordingClient()
        # bd does server-side filtering; mock returns only active issues
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with (
            patch(
                "punt_lux.apps._beads_payload.subprocess.run",
                return_value=_mock_bd_result(active),
            ),
            patch("punt_lux.show.LuxRestClient.connect", return_value=client),
        ):
            result = runner.invoke(app, ["show", "beads"])

        assert result.exit_code == 0
        assert "2 issues" in result.output
        assert client.request is not None
        assert client.request.scene_id.startswith("beads-")  # project-scoped tab

    def test_show_beads_reports_a_render_rejection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A reachable luxd that refuses the render surfaces the reason, exit 1."""
        monkeypatch.chdir(tmp_path)
        client = _RejectingClient("duplicate element id 'table'")
        with (
            patch(
                "punt_lux.apps._beads_payload.subprocess.run",
                return_value=_mock_bd_result(_ISSUES),
            ),
            patch("punt_lux.show.LuxRestClient.connect", return_value=client),
        ):
            result = runner.invoke(app, ["show", "beads"])

        assert result.exit_code == 1
        assert "Beads board not shown: duplicate element id 'table'" in result.stderr

    def test_show_beads_reports_luxd_down(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """luxd unreachable is one actionable line and a non-zero exit.

        The real ``LuxRestClient.connect`` runs with no port file, so the CLI
        surfaces the production message — hint included — not a test string.
        """
        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "punt_lux.apps._beads_payload.subprocess.run",
                return_value=_mock_bd_result(_ISSUES),
            ),
            patch("punt_lux.hub_paths.HubPaths.read_port", return_value=None),
        ):
            result = runner.invoke(app, ["show", "beads"])

        assert result.exit_code == 1
        assert "luxd is not running" in result.stderr
        assert "lux hub-install" in result.stderr

    def test_show_beads_reports_render_time_unreachability(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """luxd vanishing between connect and render is one line, exit 1, no trace.

        The guard must wrap the render call, not just connect — a stale port,
        refused connection, or stall surfaces from render, and it must reach the
        user as the actionable one-liner, never an escaped traceback.
        """
        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "punt_lux.apps._beads_payload.subprocess.run",
                return_value=_mock_bd_result(_ISSUES),
            ),
            patch(
                "punt_lux.show.LuxRestClient.connect",
                return_value=_UnreachableClient(),
            ),
        ):
            result = runner.invoke(app, ["show", "beads"])

        assert result.exit_code == 1
        assert "luxd is not reachable" in result.stderr
        # The error was caught and turned into a clean exit, not re-raised.
        assert not isinstance(result.exception, HubUnavailableError)

    def test_show_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["show"])
        assert result.exit_code in {0, 2}
        assert "beads" in result.output.lower()
