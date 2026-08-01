"""BeadsService — what a click on a session's Beads entry produces.

A click always renders something. Issues become the table the Hub composes; a
``bd`` failure becomes the board's red message; an unforeseen failure becomes a
message too, because a click that produces nothing visible is indistinguishable
from a broken menu. The service is driven with a stubbed source and a recording
client, so no ``bd`` and no Hub are involved.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsFailure, BeadsResult, BeadsRows
from punt_lux.beads_service import BeadsService
from punt_lux.operations import (
    FrameRaise,
    OpError,
    RenderRequest,
    RenderTableRequest,
)
from punt_lux.operations.models.scene_results import SceneShown

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

    def load(self, *, all_issues: bool = False) -> BeadsResult:
        self._journal.note("load")
        if self._raises:
            raise RuntimeError("bd blew up in a way the loader does not model")
        return self._result


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


def _service(source: _Source) -> BeadsService:
    return BeadsService(BeadsBoard.for_project("lux"), source)


def test_the_entry_is_named_for_what_it_shows() -> None:
    service = BeadsService.for_repo()
    assert service.callback_id == "beads"
    assert service.label == "Beads"


def test_issues_are_pushed_through_the_table_route() -> None:
    """The Hub must construct the board's chrome, so the table route carries data."""
    client = _RecordingClient()
    _service(_Source(BeadsRows.of([_ISSUE]))).service(client)  # type: ignore[arg-type]  # structural stand-in for LuxRestClient

    assert len(client.tables) == 1
    assert client.scenes == []
    table = client.tables[0]
    assert table.scene_id == "beads-lux"  # the repository's one board
    assert table.frame_id == "beads-lux"
    assert [row[0] for row in table.rows] == ["lux-1"]


def test_a_bd_failure_renders_the_reason_in_the_window() -> None:
    client = _RecordingClient()
    _service(_Source(BeadsFailure("bd: command not found"))).service(client)  # type: ignore[arg-type]  # structural stand-in

    assert client.tables == []
    assert len(client.scenes) == 1
    assert "bd: command not found" in str(client.scenes[0].elements)


def test_an_empty_board_still_renders() -> None:
    client = _RecordingClient()
    _service(_Source(BeadsRows.of([]))).service(client)  # type: ignore[arg-type]  # structural stand-in

    assert len(client.scenes) == 1
    assert "No active issues." in str(client.scenes[0].elements)


def test_an_unforeseen_failure_renders_rather_than_vanishing() -> None:
    """A click that produces nothing visible reads to the user as a broken menu."""
    client = _RecordingClient()
    _service(_Source(raises=True)).service(client)  # type: ignore[arg-type]  # structural stand-in

    assert len(client.scenes) == 1
    assert "could not be built" in str(client.scenes[0].elements)


def test_a_refused_render_is_reported_not_raised() -> None:
    """The servicing thread survives a Hub refusal; there is nowhere to render it."""
    client = _RecordingClient(refuse=True)
    _service(_Source(BeadsRows.of([_ISSUE]))).service(client)  # type: ignore[arg-type]  # structural stand-in

    assert len(client.tables) == 1  # the attempt happened and did not raise


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

    service.acknowledge(client)  # type: ignore[arg-type]  # structural stand-in
    service.service(client)  # type: ignore[arg-type]  # structural stand-in

    assert journal.steps == ("raise", "load", "render_table")
    assert client.scenes == []  # a board that is up needs no placeholder


def test_a_click_with_no_board_up_opens_one_before_asking_bd_anything() -> None:
    """The cold click: there is no frame to raise, so one is put up immediately."""
    journal = _Journal()
    client = _RecordingClient(journal=journal, frame_is_up=False)
    service = _service(_Source(BeadsRows.of([_ISSUE]), journal=journal))

    service.acknowledge(client)  # type: ignore[arg-type]  # structural stand-in
    service.service(client)  # type: ignore[arg-type]  # structural stand-in

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

    service.acknowledge(client)  # type: ignore[arg-type]  # structural stand-in
    service.service(client)  # type: ignore[arg-type]  # structural stand-in

    assert journal.steps == ("raise", "load", "render_table")
