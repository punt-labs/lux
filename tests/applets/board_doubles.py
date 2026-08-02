"""The stand-ins a board test drives: a source, a client, and the order of both.

A board's tests run with no ``bd`` and no Hub. What they need instead is a source
that returns a preset run, a client that records what was pushed to it, and a way
to say which happened first — because the order is most of what these contracts
are about, from "the user saw something before the database was asked" to "the
board was kept even though the push never landed".

They live here rather than in one test module because two modules drive the same
pair: :mod:`tests.applets.test_beads_service` through the service, and
:mod:`tests.applets.test_board_cache` through the cache underneath it.
"""

from __future__ import annotations

import threading
from typing import Self, final

from punt_lux.apps.bd_command import BdOutput
from punt_lux.apps.beads_load import BeadsLoad
from punt_lux.apps.beads_result import BeadsFailure, BeadsResult, BeadsRows
from punt_lux.operations import FrameRaise, OpError, RenderRequest, RenderTableRequest
from punt_lux.operations.models.scene_results import SceneShown
from punt_lux.rest_transport import HubUnavailableError

__all__ = [
    "BD_MS",
    "GATE_SECONDS",
    "ISSUE",
    "PARSE_MS",
    "SPAWN_MS",
    "Gated",
    "Journal",
    "RecordingClient",
    "Source",
    "ThenFails",
    "UnraisableClient",
    "loaded",
]

ISSUE = {
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
SPAWN_MS = 9.0
BD_MS = 4820.0
PARSE_MS = 44.0


def loaded(result: BeadsResult) -> BeadsLoad:
    """A completed run: the preset result, and figures for where its time went."""
    return BeadsLoad(result, BdOutput("[]", SPAWN_MS, BD_MS), PARSE_MS)


@final
class Journal:
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
class Source:
    """A beads source returning a preset load result, or raising instead."""

    _result: BeadsResult
    _raises: bool
    _journal: Journal
    __slots__ = ("_journal", "_raises", "_result")

    def __new__(
        cls,
        result: BeadsResult | None = None,
        *,
        raises: bool = False,
        journal: Journal | None = None,
    ) -> Self:
        self = super().__new__(cls)
        # Absent means the empty board — the default this stands in for.
        self._result = result if result is not None else BeadsRows.of([])
        self._raises = raises
        # Absent means a test that does not care about ordering; it still records.
        self._journal = journal if journal is not None else Journal()
        return self

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        self._journal.note("load")
        if self._raises:
            raise RuntimeError("bd blew up in a way the loader does not model")
        return loaded(self._result)


@final
class ThenFails:
    """A source that reads once and then cannot — the shape a stale board is for.

    The prefetch gets a board; every load after it fails. That is a ``bd`` that
    worked at spawn and stopped working, which is the case the held board exists
    to survive.
    """

    _first: BeadsResult
    _loads: int
    _journal: Journal
    __slots__ = ("_first", "_journal", "_loads")

    def __new__(cls, first: BeadsResult, journal: Journal) -> Self:
        self = super().__new__(cls)
        self._first = first
        self._loads = 0
        self._journal = journal
        return self

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        self._journal.note("load")
        self._loads += 1
        if self._loads > 1:
            return loaded(BeadsFailure("bd: connection refused"))
        return loaded(self._first)


# How long a test waits on the other thread before giving up. Long enough that a
# loaded machine cannot trip it, short enough that a genuine hang fails the run
# rather than holding it.
GATE_SECONDS = 5.0


@final
class Gated:
    """A source whose first load hangs until released, while a later one overtakes.

    The interleaving two loading threads can produce, made deterministic. One
    load begins, hangs here, and is released only after the load that started
    behind it has finished and stored — so the two arrive in the opposite order
    to the one they began in, which is the order that decides between them.

    What the gated load ends with says which case is under test. It fails by
    default: a click whose ``bd`` died while the warm-up's board was landing.
    Given rows instead, it is the load that began first and returned last, whose
    issues are the older ones however late its board arrives.
    """

    _result: BeadsResult
    _gated: BeadsResult
    _loads: int
    _reached: threading.Event
    _released: threading.Event
    __slots__ = ("_gated", "_loads", "_reached", "_released", "_result")

    def __new__(cls, result: BeadsResult, gated: BeadsResult | None = None) -> Self:
        self = super().__new__(cls)
        self._result = result
        # Absent means the gated load fails — the case the ordering rule was
        # first written for, where nothing is held to write back.
        self._gated = (
            gated if gated is not None else BeadsFailure("bd: connection refused")
        )
        self._loads = 0
        self._reached = threading.Event()
        self._released = threading.Event()
        return self

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        """Hang the first run at the gate; answer every later one straight away."""
        self._loads += 1
        if self._loads > 1:
            return loaded(self._result)
        self._reached.set()
        self._released.wait(timeout=GATE_SECONDS)
        return loaded(self._gated)

    @property
    def loads(self) -> int:
        """How many runs this source was asked for — one ``bd`` apiece, in life."""
        return self._loads

    def reached(self) -> None:
        """Block until the gated run is in flight, so the next one crosses it."""
        assert self._reached.wait(timeout=GATE_SECONDS), "the gated load never ran"

    def release(self) -> None:
        """Let the gated run finish — and fail."""
        self._released.set()


@final
class RecordingClient:
    """A LuxRestClient stand-in recording the scene writes a service makes.

    Its three failure modes are the three a real client has, and they are not
    interchangeable: a refusal is a Hub that answered no, an unreachable Hub is
    a push that raised before any answer, and a frame that is not up is neither
    — it is the ordinary cold click.
    """

    _tables: list[RenderTableRequest]
    _scenes: list[RenderRequest]
    _refuse: bool
    _unreachable: bool
    _raises_frame: bool
    _journal: Journal
    __slots__ = (
        "_journal",
        "_raises_frame",
        "_refuse",
        "_scenes",
        "_tables",
        "_unreachable",
    )

    def __new__(
        cls,
        *,
        refuse: bool = False,
        unreachable: bool = False,
        frame_is_up: bool = True,
        journal: Journal | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._tables = []
        self._scenes = []
        self._refuse = refuse
        self._unreachable = unreachable
        self._raises_frame = frame_is_up
        # Absent means a test that does not care about ordering; it still records.
        self._journal = journal if journal is not None else Journal()
        return self

    def raise_frame(self, frame_id: str) -> FrameRaise:
        """Answer the raise — unless there is no Hub to answer it.

        A Hub that cannot be reached cannot be reached for a raise either, so an
        unreachable client fails this call the way it fails a push. The frame
        flag is about a display holding the frame, which is a different question
        and only reachable when there is a Hub to ask.
        """
        self._journal.note("raise")
        if self._unreachable:
            raise HubUnavailableError("luxd is not running on port 8430")
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
        if self._unreachable:
            raise HubUnavailableError("luxd is not running on port 8430")
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
class UnraisableClient:
    """A client whose raise cannot be answered — no display, or a timed-out trip."""

    _journal: Journal
    __slots__ = ("_journal",)

    def __new__(cls, journal: Journal) -> Self:
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
