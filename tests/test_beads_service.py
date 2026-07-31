"""BeadsService — what a click on a session's Beads entry produces.

A click always renders something. Issues become the table the Hub composes; a
``bd`` failure becomes the board's red message; an unforeseen failure becomes a
message too, because a click that produces nothing visible is indistinguishable
from a broken menu. The service is driven with a stubbed source and a recording
client, so no ``bd`` and no Hub are involved.
"""

from __future__ import annotations

from typing import Any, Self, final

from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.beads_service import BeadsService
from punt_lux.operations import OpError, RenderRequest, RenderTableRequest
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
class _Source:
    """A beads source returning a preset load result, or raising one."""

    _result: tuple[list[dict[str, Any]], str | None]
    _raises: bool
    __slots__ = ("_raises", "_result")

    def __new__(
        cls,
        result: tuple[list[dict[str, Any]], str | None] = ([], None),
        *,
        raises: bool = False,
    ) -> Self:
        self = super().__new__(cls)
        self._result = result
        self._raises = raises
        return self

    def load(
        self, *, all_issues: bool = False
    ) -> tuple[list[dict[str, Any]], str | None]:
        if self._raises:
            raise RuntimeError("bd blew up in a way the loader does not model")
        return self._result


@final
class _RecordingClient:
    """A LuxRestClient stand-in recording the scene writes a service makes."""

    _tables: list[RenderTableRequest]
    _scenes: list[RenderRequest]
    _refuse: bool
    __slots__ = ("_refuse", "_scenes", "_tables")

    def __new__(cls, *, refuse: bool = False) -> Self:
        self = super().__new__(cls)
        self._tables = []
        self._scenes = []
        self._refuse = refuse
        return self

    def render_table(self, request: RenderTableRequest) -> SceneShown | OpError:
        self._tables.append(request)
        return self._reply(request.scene_id)

    def render(self, request: RenderRequest) -> SceneShown | OpError:
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


def _service(source: _Source) -> BeadsService:
    return BeadsService(BeadsBoard.for_project("lux"), source)


def test_the_entry_is_named_for_what_it_shows() -> None:
    service = BeadsService.for_project("lux")
    assert service.callback_id == "beads"
    assert service.label == "Beads"


def test_issues_are_pushed_through_the_table_route() -> None:
    """The Hub must construct the board's chrome, so the table route carries data."""
    client = _RecordingClient()
    _service(_Source(([_ISSUE], None))).service(client)  # type: ignore[arg-type]  # structural stand-in for LuxRestClient

    assert len(client.tables) == 1
    assert client.scenes == []
    table = client.tables[0]
    assert table.scene_id == "beads-lux"  # the repository's one board
    assert table.frame_id == "beads-lux"
    assert [row[0] for row in table.rows] == ["lux-1"]


def test_a_bd_failure_renders_the_reason_in_the_window() -> None:
    client = _RecordingClient()
    _service(_Source(([], "bd: command not found"))).service(client)  # type: ignore[arg-type]  # structural stand-in

    assert client.tables == []
    assert len(client.scenes) == 1
    assert "bd: command not found" in str(client.scenes[0].elements)


def test_an_empty_board_still_renders() -> None:
    client = _RecordingClient()
    _service(_Source(([], None))).service(client)  # type: ignore[arg-type]  # structural stand-in

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
    _service(_Source(([_ISSUE], None))).service(client)  # type: ignore[arg-type]  # structural stand-in

    assert len(client.tables) == 1  # the attempt happened and did not raise
