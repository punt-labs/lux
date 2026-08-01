"""BeadsService — what a click on a session's Beads entry produces.

A click always renders something. Issues become the table the Hub composes; a
``bd`` failure with nothing loaded becomes the board's red message; an unforeseen
failure becomes a message too, because a click that produces nothing visible is
indistinguishable from a broken menu. The service is driven with a stubbed source
and a recording client, so no ``bd`` and no Hub are involved.

Once a board has loaded the click changes shape: the answer is that board rather
than a placeholder, the fresh load runs behind it, and a load that fails leaves
it standing. The tests below pin both shapes and the order within them, because
the order is the whole contract — the user must see something real before any
query begins.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_service import BeadsService
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.latency import ClickLatency
from punt_lux.apps.bd_command import BdOutput
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_load import BeadsLoad
from punt_lux.apps.beads_result import BeadsFailure, BeadsResult, BeadsRows
from punt_lux.operations import (
    FrameRaise,
    OpError,
    RenderRequest,
    RenderTableRequest,
)
from punt_lux.operations.models.scene_results import SceneShown

if TYPE_CHECKING:
    import pytest

_ISSUE = {
    "id": "lux-1",
    "title": "a thing",
    "status": "open",
    "priority": 1,
    "issue_type": "task",
    "description": "why",
    "owner": "",
    "created_at": "2026-07-31",
    "updated_at": "2026-07-31",
}


# The figures a stand-in run reports, chosen to be told apart on sight in a
# line: the spawn, the wait on bd, and the parse are each a different order of
# magnitude, so an assertion about one cannot pass on another's number.
_SPAWN_MS = 9.0
_BD_MS = 4820.0
_PARSE_MS = 44.0


def _loaded(result: BeadsResult) -> BeadsLoad:
    """A completed run: the preset result, and figures for where its time went."""
    return BeadsLoad(result, BdOutput("[]", _SPAWN_MS, _BD_MS), _PARSE_MS)


@final
class _Journal:
    """The order things happened in — which is what a click's contract is about.

    The client and the source write into one of these, so a test can assert that
    the user saw something before the database was ever asked.
    """

    _steps: list[str]
    __slots__ = ("_steps",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._steps = []
        return self

    def note(self, step: str) -> None:
        self._steps.append(step)

    @property
    def steps(self) -> tuple[str, ...]:
        return tuple(self._steps)


@final
class _Source:
    """A beads source returning a preset load result, or raising instead."""

    _result: BeadsResult
    _raises: bool
    _journal: _Journal
    __slots__ = ("_journal", "_raises", "_result")

    def __new__(
        cls,
        result: BeadsResult | None = None,
        *,
        raises: bool = False,
        journal: _Journal | None = None,
    ) -> Self:
        self = super().__new__(cls)
        # Absent means the empty board — the default this stands in for.
        self._result = result if result is not None else BeadsRows.of([])
        self._raises = raises
        # Absent means a test that does not care about ordering; it still records.
        self._journal = journal if journal is not None else _Journal()
        return self

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        self._journal.note("load")
        if self._raises:
            raise RuntimeError("bd blew up in a way the loader does not model")
        return _loaded(self._result)


@final
class _ThenFails:
    """A source that reads once and then cannot — the shape a stale board is for.

    The prefetch gets a board; every load after it fails. That is a ``bd`` that
    worked at spawn and stopped working, which is the case the held board exists
    to survive.
    """

    _first: BeadsResult
    _loads: int
    _journal: _Journal
    __slots__ = ("_first", "_journal", "_loads")

    def __new__(cls, first: BeadsResult, journal: _Journal) -> Self:
        self = super().__new__(cls)
        self._first = first
        self._loads = 0
        self._journal = journal
        return self

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        self._journal.note("load")
        self._loads += 1
        if self._loads > 1:
            return _loaded(BeadsFailure("bd: connection refused"))
        return _loaded(self._first)


@final
class _RecordingClient:
    """A LuxRestClient stand-in recording the scene writes a service makes."""

    _tables: list[RenderTableRequest]
    _scenes: list[RenderRequest]
    _refuse: bool
    _raises_frame: bool
    _journal: _Journal
    __slots__ = ("_journal", "_raises_frame", "_refuse", "_scenes", "_tables")

    def __new__(
        cls,
        *,
        refuse: bool = False,
        frame_is_up: bool = True,
        journal: _Journal | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._tables = []
        self._scenes = []
        self._refuse = refuse
        self._raises_frame = frame_is_up
        # Absent means a test that does not care about ordering; it still records.
        self._journal = journal if journal is not None else _Journal()
        return self

    def raise_frame(self, frame_id: str) -> FrameRaise:
        self._journal.note("raise")
        return FrameRaise(frame_id=frame_id, raised=self._raises_frame)

    def render_table(self, request: RenderTableRequest) -> SceneShown | OpError:
        self._journal.note("render_table")
        self._tables.append(request)
        return self._reply(request.scene_id)

    def render(self, request: RenderRequest) -> SceneShown | OpError:
        self._journal.note("render")
        self._scenes.append(request)
        return self._reply(request.scene_id)

    def _reply(self, scene_id: str) -> SceneShown | OpError:
        if self._refuse:
            return OpError(code="rejected", reason="no")
        return SceneShown(scene_id=scene_id)

    @property
    def tables(self) -> list[RenderTableRequest]:
        return self._tables

    @property
    def scenes(self) -> list[RenderRequest]:
        return self._scenes


@final
class _UnraisableClient:
    """A client whose raise cannot be answered — no display, or a timed-out trip."""

    _journal: _Journal
    __slots__ = ("_journal",)

    def __new__(cls, journal: _Journal) -> Self:
        self = super().__new__(cls)
        self._journal = journal
        return self

    def raise_frame(self, frame_id: str) -> OpError:
        self._journal.note("raise")
        return OpError(code="display_unavailable", reason="no display is running")

    def render_table(self, request: RenderTableRequest) -> SceneShown:
        self._journal.note("render_table")
        return SceneShown(scene_id=request.scene_id)

    def render(self, request: RenderRequest) -> SceneShown:
        self._journal.note("render")
        return SceneShown(scene_id=request.scene_id)


def _service(source: _Source | _ThenFails) -> BeadsService:
    return BeadsService(BoardLoad(BeadsBoard.for_project("lux"), source))


def _click(service: BeadsService, client: object) -> ClickLatency:
    """Service one click and return the clock it was timed on.

    The stand-in clients are structural, so the one cast the tests need lives
    here rather than on every call.
    """
    latency = ClickLatency("beads")
    service.service(client, latency)  # type: ignore[arg-type]  # structural stand-in
    return latency


def _whole_click(service: BeadsService, client: object) -> ClickLatency:
    """Drive both halves of a click exactly as the leg drives them.

    The answer is timed by the leg rather than by the service, so the helper
    wraps it here too — a click whose answer went untimed would report a line no
    real click can produce.
    """
    latency = ClickLatency("beads")
    with latency.answering():
        service.acknowledge(client, latency)  # type: ignore[arg-type]  # structural stand-in
    service.service(client, latency)  # type: ignore[arg-type]  # structural stand-in
    return latency


def _reported(caplog: pytest.LogCaptureFixture) -> str:
    """The line the click's clock reported, whatever else was logged around it."""
    return caplog.records[-1].getMessage()


def test_the_entry_is_named_for_what_it_shows() -> None:
    service = BeadsService.for_repo()
    assert service.callback_id == "beads"
    assert service.label == "Beads"


def test_issues_are_pushed_through_the_table_route() -> None:
    """The Hub must construct the board's chrome, so the table route carries data."""
    client = _RecordingClient()
    _click(_service(_Source(BeadsRows.of([_ISSUE]))), client)

    assert len(client.tables) == 1
    assert client.scenes == []
    table = client.tables[0]
    assert table.scene_id == "beads-lux"  # the repository's one board
    assert table.frame_id == "beads-lux"
    assert [row[0] for row in table.rows] == ["lux-1"]


def test_a_bd_failure_renders_the_reason_in_the_window() -> None:
    client = _RecordingClient()
    _click(_service(_Source(BeadsFailure("bd: command not found"))), client)

    assert client.tables == []
    assert len(client.scenes) == 1
    assert "bd: command not found" in str(client.scenes[0].elements)


def test_an_empty_board_still_renders() -> None:
    client = _RecordingClient()
    _click(_service(_Source(BeadsRows.of([]))), client)

    assert len(client.scenes) == 1
    assert "No active issues." in str(client.scenes[0].elements)


def test_an_unforeseen_failure_renders_rather_than_vanishing() -> None:
    """A click that produces nothing visible reads to the user as a broken menu."""
    client = _RecordingClient()
    _click(_service(_Source(raises=True)), client)

    assert len(client.scenes) == 1
    assert "could not be built" in str(client.scenes[0].elements)


def test_a_refused_render_is_reported_not_raised() -> None:
    """The servicing thread survives a Hub refusal; there is nowhere to render it."""
    client = _RecordingClient(refuse=True)
    _click(_service(_Source(BeadsRows.of([_ISSUE]))), client)

    assert len(client.tables) == 1  # the attempt happened and did not raise


def test_the_stages_behind_the_answer_are_timed_one_by_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A board that took a while has to name which of its stages took it.

    The query goes to a hosted database, the build is local, and the push is a
    round trip to luxd — three different problems wearing one wait. Timing them
    separately is what turns "it took a while" into which of the three it was.
    """
    client = _RecordingClient()
    latency = _click(_service(_Source(BeadsRows.of([_ISSUE]))), client)

    with caplog.at_level(logging.INFO):
        latency.report()

    line = _reported(caplog)
    assert line.index("fetched") < line.index("built") < line.index("pushed")


def test_the_fetch_says_which_side_of_the_subprocess_the_time_went(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A four-second fetch is two different problems, and the line says which.

    Everything lux does around ``bd`` is attributed — starting the process,
    waiting on it, reading what came back — so a slow board names the slow part
    instead of leaving "the query" to carry the blame for all three. ``bd``'s own
    wall time stays one figure: its inside is not ours to instrument.
    """
    client = _RecordingClient()
    latency = _click(_service(_Source(BeadsRows.of([_ISSUE]))), client)

    with caplog.at_level(logging.INFO):
        latency.report()

    line = _reported(caplog)
    assert "spawn 9" in line
    assert "bd 4820" in line
    assert "parse 44" in line
    assert "1 rows" in line
    assert line.index("spawn") < line.index("bd 4820") < line.index("parse")
    # And it belongs to the stage that did it, not to the click at large.
    assert "fetched" in line[: line.index("spawn")]


def test_the_refresh_behind_a_standing_board_is_decomposed_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reload nobody waits on still says where it went; it is the same query."""
    client = _RecordingClient(frame_is_up=False)
    service = _service(_Source(BeadsRows.of([_ISSUE])))

    service.prefetch()
    latency = _whole_click(service, client)

    with caplog.at_level(logging.INFO):
        latency.report()

    line = _reported(caplog)
    assert "refreshed" in line[: line.index("spawn")]
    assert "spawn 9" in line
    assert "bd 4820" in line
    assert "parse 44" in line


def test_a_load_that_fails_times_the_stage_it_failed_in_and_no_later_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """How far the click got is the first thing to know about a click that broke."""
    client = _RecordingClient()
    latency = _click(_service(_Source(raises=True)), client)

    with caplog.at_level(logging.INFO):
        latency.report()

    line = _reported(caplog)
    assert "fetched" in line
    assert "built" not in line  # the build never ran; nothing claims it did
    assert "pushed" in line  # but the failure message reached the window


def test_a_click_on_a_board_already_up_raises_it_before_asking_bd_anything() -> None:
    """The common click, and the one the response budget is written for.

    Reading the issues is a query to a hosted database and takes as long as it
    takes. Running it first is what made a click look like nothing had happened:
    the board was already on screen, and the user waited on a database to be told
    so. The frame is raised first, and the load runs behind it.
    """
    journal = _Journal()
    client = _RecordingClient(journal=journal, frame_is_up=True)
    service = _service(_Source(BeadsRows.of([_ISSUE]), journal=journal))

    _whole_click(service, client)

    assert journal.steps == ("raise", "load", "render_table")
    assert client.scenes == []  # a board that is up needs no placeholder


def test_a_click_with_no_board_up_opens_one_before_asking_bd_anything() -> None:
    """The cold click: there is no frame to raise, so one is put up immediately."""
    journal = _Journal()
    client = _RecordingClient(journal=journal, frame_is_up=False)
    service = _service(_Source(BeadsRows.of([_ISSUE]), journal=journal))

    _whole_click(service, client)

    assert journal.steps == ("raise", "render", "load", "render_table")
    assert "Loading issues" in str(client.scenes[0].elements)
    assert client.scenes[0].frame is not None
    assert client.scenes[0].frame.frame_id == client.tables[0].frame_id


def test_a_raise_that_cannot_be_answered_leaves_a_good_board_alone() -> None:
    """A failed round trip must not replace a board that is up with a placeholder.

    The raise can fail while the board is perfectly visible — no display, a
    timed-out round trip. Pushing the placeholder on the strength of that would
    blank a good board for as long as the load takes, so nothing is pushed and the
    click degrades to what it did before it had an instant half at all.
    """
    journal = _Journal()
    client = _UnraisableClient(journal)
    service = _service(_Source(BeadsRows.of([_ISSUE]), journal=journal))

    _whole_click(service, client)

    assert journal.steps == ("raise", "load", "render_table")


def test_a_prefetched_board_is_shown_before_the_fresh_load_begins() -> None:
    """The click the whole warm-up is for: the answer is a board, not a word.

    A cold click opens "Loading issues…" and the user reads it for as long as the
    query takes — measured at ~4.9 s against the hosted database. With a board
    already loaded there is something real to put up instead, and it goes up
    before the fresh query starts rather than after it returns.
    """
    journal = _Journal()
    client = _RecordingClient(journal=journal, frame_is_up=False)
    service = _service(_Source(BeadsRows.of([_ISSUE]), journal=journal))

    service.prefetch()
    _whole_click(service, client)

    # The board is pushed between the raise and the click's own load — the two
    # facts that make it an answer rather than a result.
    assert journal.steps == ("load", "raise", "render_table", "load", "render_table")
    assert client.scenes == []  # and no placeholder was shown at any point


def test_a_click_says_when_its_answer_was_a_board_it_already_had(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two clicks with the same figures are not the same click.

    Answering in 28 ms with the board reads differently from answering in 28 ms
    with the word "Loading", and the load behind them is a wait in one case and
    not in the other. The line says which, and times the load as one figure
    because no stage of it is the user's problem.
    """
    client = _RecordingClient(frame_is_up=False)
    service = _service(_Source(BeadsRows.of([_ISSUE])))

    service.prefetch()
    latency = _whole_click(service, client)

    with caplog.at_level(logging.INFO):
        latency.report()

    line = _reported(caplog)
    assert "answered" in line
    assert "(cached board)" in line
    assert "refreshed" in line
    assert "fetched" not in line  # nobody watched the stages; they are one figure


def test_a_load_that_fails_leaves_the_board_on_screen_standing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A board a few minutes old beats a red message where the board was.

    The user asked to look at their issues. The ones from the last load are still
    very nearly the answer, so a ``bd`` that has stopped answering costs a log
    line rather than the board.
    """
    journal = _Journal()
    client = _RecordingClient(journal=journal, frame_is_up=False)
    service = _service(_ThenFails(BeadsRows.of([_ISSUE]), journal))

    service.prefetch()
    with caplog.at_level(logging.WARNING):
        _whole_click(service, client)

    assert client.scenes == []  # no red message replaced the board
    assert len(client.tables) == 1  # only the answer was pushed; nothing after it
    assert "the one on screen stands" in caplog.text
    assert "bd: connection refused" in caplog.text


def test_a_board_that_could_not_be_prefetched_leaves_the_click_cold(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed warm-up holds nothing: the next click must not answer with it."""
    journal = _Journal()
    client = _RecordingClient(journal=journal, frame_is_up=False)
    service = _service(_Source(BeadsFailure("bd: command not found"), journal=journal))

    with caplog.at_level(logging.WARNING):
        service.prefetch()
    _whole_click(service, client)

    assert "ahead of the first click" in caplog.text
    assert journal.steps == ("load", "raise", "render", "load", "render")
    assert "Loading issues" in str(client.scenes[0].elements)  # the cold answer
    assert "bd: command not found" in str(client.scenes[1].elements)
