"""Unit tests for the ``lux beads`` command and its supporting apps."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, final
from unittest.mock import patch

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from punt_lux.__main__ import app
from punt_lux.apps._beads_payload import BeadsPayloadBuilder
from punt_lux.apps.beads import BeadsBrowser
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_load import BeadsLoad
from punt_lux.apps.beads_result import BeadsFailure, BeadsResult, BeadsRows
from punt_lux.cli.beads import BeadsBoardCommand
from punt_lux.operations import (
    OpError,
    RenderRequest,
    RenderTableRequest,
    SceneShown,
)
from punt_lux.rest_transport import HubUnavailableError

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


@final
class _FakeProcess:
    """A stand-in for the ``bd`` process, spawned and waited on separately.

    The loader uses ``Popen`` rather than ``subprocess.run`` so it can time the
    spawn apart from the wait, which means the stand-in answers ``communicate``
    rather than being a finished ``CompletedProcess``. It records the timeout it
    was waited with and whether it was killed, because both are contracts: a
    ``bd`` that overruns must be ended, not left behind.
    """

    _out: str
    _err: str
    _overruns: bool
    returncode: int
    waited_with: float | None  # None until communicate is called
    killed: bool
    __slots__ = ("_err", "_out", "_overruns", "killed", "returncode", "waited_with")

    def __new__(
        cls, out: str, err: str = "", code: int = 0, *, overruns: bool = False
    ) -> Self:
        self = super().__new__(cls)
        self._out = out
        self._err = err
        self._overruns = overruns
        self.returncode = code
        self.waited_with = None
        self.killed = False
        return self

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.waited_with = timeout
        if self._overruns and not self.killed:
            raise subprocess.TimeoutExpired(cmd="bd list --json", timeout=timeout or 0)
        return self._out, self._err

    def kill(self) -> None:
        self.killed = True


def _bd_wrote(issues: list[dict[str, Any]]) -> _FakeProcess:
    """A ``bd`` that answered with these issues as JSON."""
    return _FakeProcess(json.dumps(issues))


def _spawns(process: _FakeProcess) -> Any:  # the patch context manager
    """Patch the spawn so ``bd`` is never really run, and return the process."""
    return patch("punt_lux.apps.bd_command.subprocess.Popen", return_value=process)


# ---------------------------------------------------------------------------
# load_beads
# ---------------------------------------------------------------------------


def _rows(load: BeadsLoad) -> list[dict[str, Any]]:
    """Narrow a load to its rows; a failure here means the load itself failed."""
    result = load.result
    assert isinstance(result, BeadsRows), result
    return result.issues


class TestLoadBeads:
    def test_filters_closed_by_default(self) -> None:
        # bd does the filtering server-side; the fake returns only active issues
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with _spawns(_bd_wrote(active)):
            result = _rows(BeadsBrowser().load())
        assert len(result) == 2
        assert all(i["status"] in {"open", "in_progress"} for i in result)

    def test_all_flag_includes_closed(self) -> None:
        with _spawns(_bd_wrote(_ISSUES)):
            result = _rows(BeadsBrowser().load(all_issues=True))
        assert len(result) == 3

    def test_sorted_in_progress_first_then_priority(self) -> None:
        with _spawns(_bd_wrote(_ISSUES)):
            result = _rows(BeadsBrowser().load(all_issues=True))
        assert result[0]["id"] == "beads-002"  # in_progress floats to top
        assert result[1]["id"] == "beads-001"  # P1, open

    def test_default_floats_in_progress_above_open(self) -> None:
        # The default board query returns open + in_progress issues; the
        # in_progress bead must float to the top even though its priority is
        # lower than an open bead's, exercising the default-path sort.
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with _spawns(_bd_wrote(active)):
            result = _rows(BeadsBrowser().load())
        assert [i["id"] for i in result] == ["beads-002", "beads-001"]
        assert result[0]["status"] == "in_progress"
        assert result[1]["priority"] < result[0]["priority"]  # P1 open below P2

    def test_subprocess_failure_returns_empty(self) -> None:
        with _spawns(_FakeProcess("", "db locked", 1)):
            outcome = BeadsBrowser().load().result
        assert isinstance(outcome, BeadsFailure)
        assert "db locked" in outcome.reason

    def test_defaults_applied(self) -> None:
        with _spawns(_bd_wrote([{"id": "beads-100"}])):
            result = _rows(BeadsBrowser().load())
        assert result[0]["status"] == "open"
        assert result[0]["priority"] == 4
        assert result[0]["issue_type"] == "task"

    def test_empty_stdout_returns_empty(self) -> None:
        with _spawns(_FakeProcess("")):
            outcome = BeadsBrowser().load().result
        assert isinstance(outcome, BeadsFailure)
        assert "no output" in outcome.reason

    def test_invalid_json_returns_empty(self) -> None:
        with _spawns(_FakeProcess("not-json")):
            outcome = BeadsBrowser().load().result
        assert isinstance(outcome, BeadsFailure)
        assert "JSON" in outcome.reason or "malformed" in outcome.reason

    def test_unexpected_json_shape_returns_error(self) -> None:
        with _spawns(_FakeProcess(json.dumps({"issues": _ISSUES}))):
            outcome = BeadsBrowser().load().result
        assert isinstance(outcome, BeadsFailure)
        assert "unexpected JSON shape" in outcome.reason

    def test_subprocess_timeout_returns_error(self) -> None:
        with _spawns(_FakeProcess("", overruns=True)):
            outcome = BeadsBrowser().load().result
        assert isinstance(outcome, BeadsFailure)
        assert "timed out" in outcome.reason

    def test_a_bd_that_overran_is_killed_and_reaped(self) -> None:
        """A process left behind outlives the click that started it."""
        process = _FakeProcess("", overruns=True)
        with _spawns(process):
            BeadsBrowser().load()
        assert process.killed

    def test_non_dict_entries_dropped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        wrote = _FakeProcess(json.dumps([{"id": "beads-001", "title": "ok"}, "x", 42]))
        with (
            caplog.at_level("WARNING", logger="punt_lux.apps._beads_payload"),
            _spawns(wrote),
        ):
            outcome = BeadsBrowser().load().result
        assert isinstance(outcome, BeadsRows)
        assert len(outcome) == 1
        assert "dropped 2 non-dict entries" in caplog.text

    def test_passes_all_flag_to_bd(self) -> None:
        with _spawns(_bd_wrote(_ISSUES)) as spawn:
            BeadsBrowser().load(all_issues=True)
        assert "--all" in spawn.call_args[0][0]

    def test_default_invokes_bd_list_active(self) -> None:
        with _spawns(_bd_wrote(_ISSUES)) as spawn:
            BeadsBrowser().load()
        args = spawn.call_args[0][0]
        assert args == ["bd", "list", "--json", "--status", "open,in_progress"]

    def test_all_flag_invokes_bd_list_all(self) -> None:
        with _spawns(_bd_wrote(_ISSUES)) as spawn:
            BeadsBrowser().load(all_issues=True)
        assert spawn.call_args[0][0] == ["bd", "list", "--json", "--all"]

    def test_the_wait_on_bd_is_bounded_at_60_seconds(self) -> None:
        """The bound is on the wait now, not on the spawn: Popen never blocks."""
        process = _bd_wrote(_ISSUES)
        with _spawns(process):
            BeadsBrowser().load()
        assert process.waited_with == 60

    def test_bd_not_found_returns_empty(self) -> None:
        with patch(
            "punt_lux.apps.bd_command.subprocess.Popen",
            side_effect=FileNotFoundError("bd not found"),
        ):
            outcome = BeadsBrowser().load().result
        assert isinstance(outcome, BeadsFailure)
        reason = outcome.reason.lower()
        assert "not found" in reason or "no such file" in reason

    def test_a_load_reports_where_its_time_went(self) -> None:
        """The figures the click's line carries: lux's own, and bd's one number."""
        with _spawns(_bd_wrote(_ISSUES)):
            summary = BeadsBrowser().load(all_issues=True).summary()
        assert summary.index("spawn") < summary.index("bd ") < summary.index("parse")
        assert "3 rows" in summary
        assert " B" in summary or " kB" in summary

    def test_a_failed_load_has_no_figures_to_report(self) -> None:
        """Nothing ran, so nothing is claimed: zeros rather than invented numbers."""
        with _spawns(_FakeProcess("", "db locked", 1)):
            summary = BeadsBrowser().load().summary()
        assert "spawn 0" in summary
        assert "bd 0" in summary
        assert "0 rows" in summary


# ---------------------------------------------------------------------------
# build_beads_payload
# ---------------------------------------------------------------------------


class TestBuildBeadsPayload:
    def test_columns(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = BeadsPayloadBuilder().build(active)
        assert payload["columns"] == ["ID", "Title", "Status", "P", "Type"]

    def test_rows_match_issues(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = BeadsPayloadBuilder().build(active)
        assert len(payload["rows"]) == 2
        assert payload["rows"][0][0] == "beads-001"
        assert payload["rows"][0][3] == "P1"

    def test_detail_body_separates_the_metadata_table_from_the_description(
        self,
    ) -> None:
        # The detail pane is a two-column metadata table, a horizontal rule, then
        # the description as its own text — not one inline run of fields + prose.
        payload = BeadsPayloadBuilder().build([_ISSUES[0]])
        body = payload["detail"]["body"][0]
        table, _, description = body.partition("\n\n---\n\n")
        assert "| Field | Value |" in table
        assert "| ID | beads-001 |" in table
        assert "| Priority | P1 |" in table
        # Dates are truncated to the day inside the metadata table.
        assert "| Created | 2026-03-01 |" in table
        assert "| Updated | 2026-03-09 |" in table
        # The description body is the issue's own text, kept below the rule.
        assert description == "Login fails on slow networks."

    def test_detail_body_degrades_when_the_description_is_empty(self) -> None:
        active = [_ISSUES[1]]  # description is ""
        body = BeadsPayloadBuilder().build(active)["detail"]["body"][0]
        _, sep, description = body.partition("\n\n---\n\n")
        assert sep  # the rule still separates the fields from the placeholder
        assert description == "_No description._"

    def test_detail_body_shows_unassigned_owner(self) -> None:
        active = [_ISSUES[1]]  # owner is ""
        body = BeadsPayloadBuilder().build(active)["detail"]["body"][0]
        assert "| Owner | unassigned |" in body

    def test_filters_include_unique_values(self) -> None:
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        payload = BeadsPayloadBuilder().build(active)
        status_filter = payload["filters"][1]
        assert status_filter["items"][0] == "All"
        assert "in_progress" in status_filter["items"]
        assert "open" in status_filter["items"]

    def test_empty_issues(self) -> None:
        payload = BeadsPayloadBuilder().build([])
        assert payload["rows"] == []
        assert payload["detail"]["body"] == []


# ---------------------------------------------------------------------------
# BeadsBoard.request — the data-to-request builder
# ---------------------------------------------------------------------------


class TestBoardRequest:
    _SCENE = "beads-proj"
    _TITLE = "Beads: proj"

    def _build(self, result: BeadsResult) -> RenderTableRequest | RenderRequest:
        return BeadsBoard(self._SCENE, self._TITLE).request(result)

    def test_issues_yield_a_table_request_carrying_filters_and_detail(self) -> None:
        # The board sends columns/rows/filters/detail as DATA; the Hub composes
        # the live chrome from the table route, not a pre-built element tree.
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        request = self._build(BeadsRows.of(active))
        assert isinstance(request, RenderTableRequest)
        assert request.scene_id == self._SCENE
        assert request.title == self._TITLE
        assert request.frame_id == self._SCENE
        assert request.frame_title == self._TITLE
        assert request.columns == ["ID", "Title", "Status", "P", "Type"]
        assert len(request.rows) == 2
        # The search box and both status/type combos ride as filter data.
        assert request.filters is not None
        assert {f["type"] for f in request.filters} == {"search", "combo"}
        # The drill-down detail rides one composed markdown body per row.
        assert request.detail is not None
        detail_body = request.detail["body"]
        assert isinstance(detail_body, list)
        assert len(detail_body) == 2
        # Sort/copy chrome the CLI board carried is preserved as flags.
        assert request.flags is not None
        assert "sortable" in request.flags
        assert "copy_id" in request.flags

    def test_empty_issues_yield_a_placeholder_message(self) -> None:
        request = self._build(BeadsRows.of([]))
        assert isinstance(request, RenderRequest)
        assert len(request.elements) == 1
        elem = request.elements[0]
        assert elem["id"] == "empty"
        assert "No active issues" in str(elem["content"])
        # A message renders into the same board frame as a table would.
        assert request.frame is not None
        assert request.frame.frame_id == self._SCENE

    def test_error_yields_a_visible_error_message(self) -> None:
        """When bd fails, surface the reason instead of 'No active issues'."""
        request = self._build(BeadsFailure("bd list --json: timed out after 60s"))
        assert isinstance(request, RenderRequest)
        elem = request.elements[0]
        assert elem["id"] == "beads-error"
        assert "bd unavailable" in str(elem["content"])
        assert "timed out" in str(elem["content"])
        # The error element distinguishes itself visually (a set color).
        assert elem["color"] == "#FF5555"

    def test_a_failure_renders_its_reason_not_the_empty_placeholder(self) -> None:
        """A failure and an empty board are different states, shown differently."""
        request = self._build(BeadsFailure("connection refused"))
        assert isinstance(request, RenderRequest)
        elem = request.elements[0]
        assert elem["id"] == "beads-error"
        assert "No active issues" not in str(elem["content"])


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class _RecordingClient:
    """A LuxRestClient stand-in that records the request and reports success.

    Both surfaces record into ``request``: a table board reaches ``render_table``
    and a message board reaches ``render``, so a test reads the one that fired.
    """

    def __init__(self) -> None:
        self.request: RenderTableRequest | RenderRequest | None = None

    def render(self, request: RenderRequest) -> SceneShown:
        self.request = request
        return SceneShown(scene_id=request.scene_id)

    def render_table(self, request: RenderTableRequest) -> SceneShown:
        self.request = request
        return SceneShown(scene_id=request.scene_id)


class _RejectingClient:
    """A LuxRestClient stand-in whose installs are refused by the Hub."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def render(self, request: RenderRequest) -> OpError:
        return OpError(code="rejected", reason=self._reason)

    def render_table(self, request: RenderTableRequest) -> OpError:
        return OpError(code="rejected", reason=self._reason)


class _UnreachableClient:
    """A LuxRestClient stand-in whose installs find luxd gone mid-call.

    ``connect`` only reads the port file; the socket work happens in the install
    call, so an unreachable luxd raises there, not at connect time.
    """

    def render(self, request: RenderRequest) -> SceneShown:
        raise HubUnavailableError("luxd is not reachable on port 5001 — refused")

    def render_table(self, request: RenderTableRequest) -> SceneShown:
        raise HubUnavailableError("luxd is not reachable on port 5001 — refused")


class TestBeadsBoard:
    def test_table_request_carries_the_frame_envelope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The table request names the scene and frame after the repository — the
        # repository's one board, the same scene a session's menu entry refreshes,
        # so a command and a click land in one tab rather than two identical ones.
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)
        project = tmp_path.name
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with patch(
            "punt_lux.apps.bd_command.subprocess.Popen",
            return_value=_bd_wrote(active),
        ):
            request, note = BeadsBoardCommand().request(all_issues=False)
        assert isinstance(request, RenderTableRequest)
        assert request.scene_id == f"beads-{project}"
        assert request.title == f"Beads: {project}"
        assert request.frame_id == f"beads-{project}"
        assert request.frame_title == f"Beads: {project}"
        assert note == "2 issues"

    def test_a_subdirectory_shows_the_repositorys_board_not_a_second_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One repository has one board, whichever directory the command runs in.

        The name came from the working directory, so running the command from
        ``lux/src`` opened a scene called ``beads-src`` — a second board beside
        the repository's own, with neither refreshing the other.
        """
        (tmp_path / ".git").mkdir()
        inside = tmp_path / "src" / "punt_lux"
        inside.mkdir(parents=True)
        monkeypatch.chdir(inside)
        active = [i for i in _ISSUES if i["status"] in {"open", "in_progress"}]
        with patch(
            "punt_lux.apps.bd_command.subprocess.Popen",
            return_value=_bd_wrote(active),
        ):
            request, _note = BeadsBoardCommand().request(all_issues=False)
        assert request.scene_id == f"beads-{tmp_path.name}"

    def test_bd_error_yields_a_message_request_and_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A bd failure names the error in the note and yields a message request
        # (not a table), so the CLI reports the reason instead of "0 issues".
        monkeypatch.chdir(tmp_path)
        with patch(
            "punt_lux.apps.bd_command.subprocess.Popen",
            return_value=_FakeProcess("", "db locked", 1),
        ):
            request, note = BeadsBoardCommand().request(all_issues=False)
        assert isinstance(request, RenderRequest)
        assert note.startswith("bd error:")


class TestBeadsCLI:
    def test_bd_failure_surfaces_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        client = _RecordingClient()
        with (
            patch(
                "punt_lux.apps.bd_command.subprocess.Popen",
                return_value=_FakeProcess("", "db locked", 1),
            ),
            patch("punt_lux.cli.beads.LuxRestClient.connect", return_value=client),
        ):
            result = runner.invoke(app, ["beads"])

        # When bd fails, the CLI reports the error rather than misleading "0 issues".
        # luxd still receives a message scene carrying a visible error element.
        assert result.exit_code == 0
        assert "bd error" in result.output
        assert isinstance(client.request, RenderRequest)
        ids = [e.get("id") for e in client.request.elements]
        assert "beads-error" in ids, f"expected beads-error element, got: {ids}"

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
                "punt_lux.apps.bd_command.subprocess.Popen",
                return_value=_bd_wrote(active),
            ),
            patch("punt_lux.cli.beads.LuxRestClient.connect", return_value=client),
        ):
            result = runner.invoke(app, ["beads"])

        assert result.exit_code == 0
        assert "2 issues" in result.output
        # Active issues reach the Hub as a table request the composition route
        # builds with live chrome — not a pre-composed tree through render.
        assert isinstance(client.request, RenderTableRequest)
        # The repository's one project-scoped board, whichever surface refreshed it.
        assert client.request.scene_id.startswith("beads-")

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
                "punt_lux.apps.bd_command.subprocess.Popen",
                return_value=_bd_wrote(_ISSUES),
            ),
            patch("punt_lux.cli.beads.LuxRestClient.connect", return_value=client),
        ):
            result = runner.invoke(app, ["beads"])

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
                "punt_lux.apps.bd_command.subprocess.Popen",
                return_value=_bd_wrote(_ISSUES),
            ),
            patch("punt_lux.hub_paths.HubPaths.read_port", return_value=None),
        ):
            result = runner.invoke(app, ["beads"])

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
                "punt_lux.apps.bd_command.subprocess.Popen",
                return_value=_bd_wrote(_ISSUES),
            ),
            patch(
                "punt_lux.cli.beads.LuxRestClient.connect",
                return_value=_UnreachableClient(),
            ),
        ):
            result = runner.invoke(app, ["beads"])

        assert result.exit_code == 1
        assert "luxd is not reachable" in result.stderr
        # The error was caught and turned into a clean exit, not re-raised.
        assert not isinstance(result.exception, HubUnavailableError)

    def test_show_beads_retired_no_alias(self) -> None:
        # PL-PP-1: no backwards-compat shim for the retired `lux show beads`
        # top-level group -- the verb is `lux beads` now, with no alias.
        result = runner.invoke(app, ["show", "beads"])
        assert result.exit_code == 2
        assert "no such command" in result.output.lower()

    def test_beads_help_names_the_command(self) -> None:
        result = runner.invoke(app, ["beads", "--help"])
        assert result.exit_code == 0
        assert "beads" in result.output.lower()
