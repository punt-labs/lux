"""AppletLeg — servicing a click without starving the leg's own lease.

The leg's loop does two things: it renews the session's lease, and it receives
clicks. The work a click asks for blocks — ``bd`` runs to its own timeout, the
board push is HTTP — so it must not run on that loop. If it did, a slow click
would stall the renewal until the lease lapsed, and the session's menu entry
would disappear mid-service.

Nor may the loop wait for that work: the receive loop reads the frame behind a
click only when the click's handler returns, so a click awaited there holds the
next click behind a ``bd`` query. The work behind two clicks is one piece of
work, though, so the second click is answered and stands down rather than
starting a query of its own.

The load that runs ahead of the first click blocks for the same reason and is
held to the same rule, plus one of its own: the handshake it is started from must
not wait for it either, or the entry would take as long to appear as ``bd`` takes
to answer.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.applet_board import AppletBoard
from punt_lux.applets.beads_service import BeadsService
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_slot import BoardSlot
from punt_lux.applets.leg import AppletLeg
from punt_lux.applets.runner import ServiceRunner
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsRows
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.hub_client import LuxHubClient
from punt_lux.operations import Ok, OpError
from punt_lux.protocol.messages.listen import CallbackFrame, ReadyFrame
from punt_lux.rest_transport import HubUnavailableError

from .board_doubles import GATE_SECONDS, ISSUE, Gated, RecordingClient

if TYPE_CHECKING:
    import pytest

    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.applets.latency import ClickLatency

_IDENTITY = ClientIdentity(kind="mcp-session", name="lux · lux · #1", repo="/w/lux")

# How long a test waits for something another thread has to do before calling it
# a failure, and how often it looks. Long enough that a loaded machine cannot
# trip it; short enough that a genuine hang fails the run rather than holding it.
_POLL_SECONDS = 0.01


async def _clicked(leg: AppletLeg, callback_id: str = "beads") -> None:
    """Deliver one click and wait out the work it started — a whole click.

    The leg starts a click and returns, so a test that only delivered one would
    assert against work that had not run yet — or, under ``asyncio.run``, work
    that was cancelled on the way out.
    """
    await leg._on_callback(callback_id)
    await leg._underway.drained()


async def _said(caplog: pytest.LogCaptureFixture, phrase: str) -> None:
    """Wait until some click's line reports *phrase*, or fail.

    A click that has finished says so on its own line, and that line is the only
    thing a finished click leaves behind — which makes it what a test waits for
    when it needs one click to be over while another is still running.
    """
    for _ in range(int(GATE_SECONDS / _POLL_SECONDS)):
        if phrase in caplog.text:
            return
        await asyncio.sleep(_POLL_SECONDS)
    raise AssertionError(f"no click said {phrase!r} within {GATE_SECONDS}s")


@final
class _SlowService:
    """A service whose click work blocks a worker thread until released."""

    _started: threading.Event
    _release: threading.Event
    _serviced: int
    __slots__ = ("_release", "_serviced", "_started")

    def __new__(cls, started: threading.Event, release: threading.Event) -> Self:
        self = super().__new__(cls)
        self._started = started
        self._release = release
        self._serviced = 0
        return self

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    @property
    def frame_id(self) -> str:
        return "beads-test"

    def prefetch(self) -> None:
        """Nothing to warm: this service exists to exercise the click."""

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        """Instant by construction: the phase under a budget never blocks."""

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        self._started.set()
        self._release.wait(timeout=5)
        self._serviced += 1

    @property
    def serviced(self) -> int:
        return self._serviced


@final
class _WarmingService:
    """A service whose prefetch blocks a worker thread until it is released."""

    _started: threading.Event
    _release: threading.Event
    _prefetched: int
    __slots__ = ("_prefetched", "_release", "_started")

    def __new__(cls, started: threading.Event, release: threading.Event) -> Self:
        self = super().__new__(cls)
        self._started = started
        self._release = release
        self._prefetched = 0
        return self

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    @property
    def frame_id(self) -> str:
        return "beads-test"

    def prefetch(self) -> None:
        self._started.set()
        self._release.wait(timeout=5)
        self._prefetched += 1

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        """Not under test here: this service exists to exercise the warm-up."""

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        """Not under test here: this service exists to exercise the warm-up."""

    @property
    def prefetched(self) -> int:
        return self._prefetched


@final
class _ExplodingWarmUp:
    """A service whose warm-up raises something nobody modelled."""

    __slots__ = ()

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    @property
    def frame_id(self) -> str:
        return "beads-test"

    def prefetch(self) -> None:
        raise RuntimeError("something nobody modelled")

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        """The failure under test is in the warm-up, not in answering a click."""

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        """The failure under test is in the warm-up, not in the click's work."""


@final
class _RefusingClient:
    """A REST client stand-in whose registration is refused."""

    __slots__ = ()

    def register_callback(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> OpError:
        return OpError(code="push_required", reason="no listen leg")


@final
class _AcceptingClient:
    """A REST client stand-in whose registration puts the entry up."""

    __slots__ = ()

    def register_callback(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> Ok:
        return Ok()


@final
class _RecordingRegistration:
    """A REST client stand-in recording exactly what registration sent it."""

    _calls: list[tuple[str, str, str | None]]
    __slots__ = ("_calls",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._calls = []
        return self

    def register_callback(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> Ok:
        self._calls.append((callback_id, label, frame_id))
        return Ok()

    @property
    def calls(self) -> tuple[tuple[str, str, str | None], ...]:
        return tuple(self._calls)


def _patch_rest(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    """Point the leg's and runner's per-use Hub connection at a stand-in.

    ``AppletLeg._rest`` (registration) and ``ServiceRunner._rest`` (click
    work) each build their own connection per use, so both are patched
    directly to the same stand-in rather than patching the transport they
    build it from -- the stand-in serves whichever of the two a given test
    exercises.
    """

    def _stand_in_leg(self: AppletLeg) -> object:
        return client

    def _stand_in_runner(self: ServiceRunner) -> object:
        return client

    monkeypatch.setattr(AppletLeg, "_rest", _stand_in_leg)
    monkeypatch.setattr(ServiceRunner, "_rest", _stand_in_runner)


def test_a_slow_click_does_not_stall_the_loop_that_holds_the_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property the lease depends on: servicing runs off the leg's loop.

    While the service is blocked, the loop must still be running other work — the
    keepalive, in production. A ticker stands in for it: if servicing ran on the
    loop, the ticker could not advance while the click is in flight.
    """
    started, release = threading.Event(), threading.Event()
    service = _SlowService(started, release)
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, service)

    async def _drive() -> int:
        ticks = 0
        await leg._on_callback("beads")
        await asyncio.to_thread(started.wait, 5)  # the work has begun and blocked
        for _ in range(5):  # the loop keeps running while the work blocks
            await asyncio.sleep(0)
            ticks += 1
        # The assertion that makes this bite: the work is STILL blocked, and the
        # loop advanced anyway. Counting ticks alone proves nothing — work that
        # ran on the loop would simply finish first and let them run afterwards.
        assert service.serviced == 0
        release.set()
        await leg._underway.drained()
        return ticks

    assert asyncio.run(_drive()) == 5
    assert service.serviced == 1  # and the work still completed


def test_an_unknown_callback_is_reported_and_not_serviced(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    started, release = threading.Event(), threading.Event()
    release.set()
    service = _SlowService(started, release)
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, service)

    with caplog.at_level(logging.WARNING):
        asyncio.run(_clicked(leg, "something-else"))

    assert service.serviced == 0
    assert "no service for callback" in caplog.text


def test_a_refused_registration_is_reported_and_the_session_continues(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed register must not raise: the listen leg has to stay up either way."""
    started, release = threading.Event(), threading.Event()
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, _SlowService(started, release))

    with caplog.at_level(logging.ERROR):
        asyncio.run(leg._register())

    assert "menu entry was refused" in caplog.text


def test_registration_carries_the_services_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frame a click should raise Display-locally travels with registration."""
    started, release = threading.Event(), threading.Event()
    release.set()
    recording = _RecordingRegistration()
    _patch_rest(monkeypatch, recording)
    leg = AppletLeg(_IDENTITY, _SlowService(started, release))

    asyncio.run(leg._register())

    assert recording.calls == (("beads", "Beads", "beads-test"),)


def test_registration_does_not_wait_for_the_warm_up_behind_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entry appears when it always did; the load behind it is not in the way.

    ``on_connect`` is awaited before the receive loop starts and before the
    keepalive that holds the session's lease, so a prefetch awaited there would
    hold both for as long as ``bd`` takes. Registration must return with the
    warm-up still in flight — which is what this pins: the prefetch has begun and
    is blocked, and ``_register`` has already returned.
    """
    started, release = threading.Event(), threading.Event()
    service = _WarmingService(started, release)
    _patch_rest(monkeypatch, _AcceptingClient())
    leg = AppletLeg(_IDENTITY, service)

    async def _drive() -> None:
        await leg._register()  # returns with the warm-up still blocked
        await asyncio.to_thread(started.wait, 5)
        assert service.prefetched == 0
        release.set()
        await leg._underway.drained()

    asyncio.run(_drive())
    assert service.prefetched == 1  # and it still ran to completion


def test_an_entry_that_was_refused_is_not_warmed_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is nothing to prefetch for: no entry exists to be clicked."""
    started, release = threading.Event(), threading.Event()
    release.set()
    service = _WarmingService(started, release)
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, service)

    asyncio.run(leg._register())

    assert service.prefetched == 0


def test_a_warm_up_that_raises_leaves_the_leg_up(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A task nobody awaits must not swallow its own failure, or lose the leg."""
    _patch_rest(monkeypatch, _AcceptingClient())
    leg = AppletLeg(_IDENTITY, _ExplodingWarmUp())

    async def _drive() -> None:
        await leg._register()
        await leg._underway.drained()

    with caplog.at_level(logging.ERROR):
        asyncio.run(_drive())  # must not raise

    assert "the first click waits" in caplog.text


@final
class _UnreachableHub:
    """A REST client stand-in whose every call finds luxd gone."""

    __slots__ = ()

    def render(self, request: object) -> object:
        raise HubUnavailableError("the read timed out after 2.0s")

    def render_table(self, request: object) -> object:
        raise HubUnavailableError("the read timed out after 2.0s")


@final
class _PushingService:
    """A service that does what every real one does: push through its client."""

    __slots__ = ()

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    @property
    def frame_id(self) -> str:
        return "beads-test"

    def prefetch(self) -> None:
        """Nothing to warm: this service exists to exercise the push."""

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        """Nothing to answer with: this service exists to exercise the push."""

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        client.render_table(None)  # type: ignore[arg-type]  # the push is what is under test, not its payload


@final
class _ExplodingService:
    """A service whose work raises something nobody modelled."""

    __slots__ = ()

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    @property
    def frame_id(self) -> str:
        return "beads-test"

    def prefetch(self) -> None:
        """Nothing to warm: the failure under test is in the click's work."""

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        """The failure under test is in the work, not in answering the click."""

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        raise RuntimeError("something nobody modelled")


def test_a_push_that_cannot_reach_the_hub_is_reported_and_the_leg_survives(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The push is the half of a click with nowhere left to render its own failure.

    Escaping, it would end the receive loop and tear down a socket that is fine —
    one bad click costing the session its menu entry — and it would land in the
    listen loop's DEBUG line about luxd not having started yet, which is below
    this process's WARNING floor and, for a push that timed out, not even true.
    The transport's own sentence is what distinguishes the two, so it is logged.
    """
    _patch_rest(monkeypatch, _UnreachableHub())
    leg = AppletLeg(_IDENTITY, _PushingService())

    with caplog.at_level(logging.WARNING):
        asyncio.run(_clicked(leg))  # must not raise

    assert "rendered nothing" in caplog.text
    assert "the read timed out" in caplog.text  # not "luxd is not running yet"


def test_a_hub_that_vanishes_before_the_client_is_built_leaves_the_leg_up(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Building the client reads luxd's port, so `make restart` lands here too."""

    def _unreachable(self: ServiceRunner) -> object:
        raise HubUnavailableError("luxd is not running")

    monkeypatch.setattr(ServiceRunner, "_rest", _unreachable)
    started, release = threading.Event(), threading.Event()
    release.set()
    leg = AppletLeg(_IDENTITY, _SlowService(started, release))

    with caplog.at_level(logging.WARNING):
        asyncio.run(_clicked(leg))  # must not raise

    assert "unreachable" in caplog.text
    assert "rendered nothing" in caplog.text


def test_an_unforeseen_servicing_failure_does_not_tear_the_socket(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Anything at all going wrong in a click is survivable; the leg is not."""
    _patch_rest(monkeypatch, _UnreachableHub())
    leg = AppletLeg(_IDENTITY, _ExplodingService())

    with caplog.at_level(logging.ERROR):
        asyncio.run(_clicked(leg))  # must not raise

    assert "servicing a click failed" in caplog.text
    assert "the leg stays up" in caplog.text


@final
class _OrderedService:
    """A service recording which phase ran, so the leg's ordering can be pinned."""

    _steps: list[str]
    __slots__ = ("_steps",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._steps = []
        return self

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    @property
    def frame_id(self) -> str:
        return "beads-test"

    def prefetch(self) -> None:
        self._steps.append("prefetch")

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        self._steps.append("acknowledge")

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        self._steps.append("service")

    @property
    def steps(self) -> tuple[str, ...]:
        return tuple(self._steps)


def test_the_click_is_answered_before_its_work_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The order the response budget rests on, pinned at the leg.

    The visible answer is the phase under a deadline; the work behind it is not.
    Running them the other way round puts a database query between a user's click
    and any sign that it registered.
    """
    service = _OrderedService()
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, service)

    asyncio.run(_clicked(leg))

    assert service.steps == ("acknowledge", "service")


def test_the_leg_times_the_answer_it_is_the_one_holding_the_clock_for(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The contract is a number, so the leg measures it rather than assuming it.

    The answer is the stage under a budget and the leg is what wraps it: the
    service does not know it is being timed, and the stages it does time are
    named for its own work.
    """
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, _OrderedService())

    with caplog.at_level(logging.INFO):
        asyncio.run(_clicked(leg))

    assert "click beads: answered" in caplog.text


def test_a_click_that_failed_still_says_where_its_time_went(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The line a user pastes is most needed for the click that went wrong.

    Reporting it only on the way out of a clean click would lose it exactly when
    someone is asking what happened, so it is reported however the click ended.
    """
    _patch_rest(monkeypatch, _UnreachableHub())
    leg = AppletLeg(_IDENTITY, _ExplodingService())

    with caplog.at_level(logging.INFO):
        asyncio.run(_clicked(leg))

    assert "click beads: answered" in caplog.text
    assert "total" in caplog.text


@final
class _ParkedService:
    """A service that answers every click and parks the first click's work.

    Two clicks are two answers and — with the work behind them held open — one
    piece of work, so both counts are kept apart here.
    """

    _answers: list[str]
    _both: threading.Event
    _release: threading.Event
    _serviced: int
    __slots__ = ("_answers", "_both", "_release", "_serviced")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._answers = []
        self._both = threading.Event()
        self._release = threading.Event()
        self._serviced = 0
        return self

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    @property
    def frame_id(self) -> str:
        return "beads-test"

    def prefetch(self) -> None:
        """Nothing to warm: this service exists to exercise two clicks at once."""

    def acknowledge(self, client: BoardOps, latency: ClickLatency) -> None:
        self._answers.append("answered")
        if len(self._answers) == 2:
            self._both.set()

    def service(self, client: BoardOps, latency: ClickLatency) -> None:
        self._release.wait(timeout=GATE_SECONDS)
        self._serviced += 1

    def answered_both(self, timeout: float) -> bool:
        """Block until two clicks have been answered; say whether they were."""
        return self._both.wait(timeout=timeout)

    def release(self) -> None:
        """Let the parked work finish."""
        self._release.set()

    @property
    def answers(self) -> int:
        return len(self._answers)

    @property
    def serviced(self) -> int:
        return self._serviced


@final
class _Frames:
    """A connection handing the receive loop a handshake and then some clicks.

    The loop reads the frame behind a click only when that click's handler
    returns, which is the property under test — so the clicks are delivered
    through the real loop rather than by calling its handler twice.
    """

    _clicks: deque[str]
    __slots__ = ("_clicks",)

    def __new__(cls, *callback_ids: str) -> Self:
        self = super().__new__(cls)
        self._clicks = deque(callback_ids)
        return self

    async def recv(self) -> str:
        """The handshake the session opens on."""
        return ReadyFrame(connection_id="c").model_dump_json()

    async def send(self, frame: str) -> None:
        """Whatever the loop sends back — a subscribe, a keepalive — goes nowhere."""

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> str:
        if not self._clicks:
            raise StopAsyncIteration
        return CallbackFrame(callback_id=self._clicks.popleft()).model_dump_json()


def _listening(leg: AppletLeg) -> LuxHubClient:
    """The leg's handlers behind a real client, so its receive loop drives them."""
    return LuxHubClient(
        "ws://127.0.0.1:0/ws",
        _IDENTITY,
        on_callback=leg._on_callback,
        on_event=leg._on_event,
    )


def test_a_click_does_not_hold_the_click_behind_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The receive loop reads its next frame only when this click's handler returns.

    So a click awaited on that path holds the click behind it for the length of a
    ``bd`` query: the second click goes unraised and unacknowledged, which is a
    menu entry that does nothing for several seconds. Both clicks are delivered
    by the real receive loop here, and the second must be answered while the
    first one's work is still parked.
    """
    service = _ParkedService()
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, service)

    async def _drive() -> None:
        await asyncio.wait_for(
            _listening(leg)._run_session(_Frames("beads", "beads")),  # type: ignore[arg-type]  # the connection is structural; this one carries frames, not a socket
            GATE_SECONDS,
        )
        assert await asyncio.to_thread(service.answered_both, GATE_SECONDS)
        assert service.serviced == 0  # the first click's work is still parked
        service.release()
        await leg._underway.drained()

    asyncio.run(_drive())

    assert service.answers == 2
    assert service.serviced == 1  # and one of the two did the work for both


def _beads(source: Gated) -> BeadsService:
    """The real Beads service, over a source a test can hold at the query."""
    load = BoardLoad(BeadsBoard.for_project("lux"), source)
    return BeadsService(AppletBoard(load, BoardSlot()))


def _held_query() -> Gated:
    """A source whose first query hangs until released, and then returns issues.

    Both runs answer with the same rows: what is under test is how many runs
    there were, so a query that failed would answer the question with a red
    message instead of a board.
    """
    rows = BeadsRows.of([ISSUE])
    return Gated(rows, gated=rows)


async def _clicked_twice(
    leg: AppletLeg, source: Gated, caplog: pytest.LogCaptureFixture
) -> None:
    """Click, hold that click's query open across a second click, then release it.

    The second click is over before the first one's query returns — its line
    says so — which is what makes the count of queries afterwards mean what it
    says: one is the applet declining to start a second, not two that happened
    not to overlap.
    """
    await leg._on_callback("beads")
    await asyncio.to_thread(source.reached)
    await leg._on_callback("beads")
    await _said(caplog, "stood down")
    source.release()
    await leg._underway.drained()


def test_a_click_arriving_mid_query_does_not_start_a_second_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Two clicks a second apart are two answers and one ``bd``.

    The query already running reads the same issues the second click would ask
    for, and the board it produces lands in the frame that click just raised —
    so it serves both. Starting a second would fetch rows the first is already
    fetching, and a user drumming on the entry would start one per click.
    """
    source = _held_query()
    client = RecordingClient()
    _patch_rest(monkeypatch, client)
    leg = AppletLeg(_IDENTITY, _beads(source))

    with caplog.at_level(logging.INFO):
        asyncio.run(_clicked_twice(leg, source, caplog))

    assert source.loads == 1  # one query across both clicks
    assert len(client.scenes) == 2  # each click answered with its own placeholder
    assert len(client.tables) == 1  # and the one query's board went up behind them


def test_a_click_that_stood_down_reports_no_figures_for_a_query_it_never_ran(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A line naming stages this click did not spend would blame the wrong click.

    The click that stood down waited on nothing, so it reports its own answer and
    says why there is nothing after it. The query's figures belong to the click
    that started it.
    """
    source = _held_query()
    _patch_rest(monkeypatch, RecordingClient())
    leg = AppletLeg(_IDENTITY, _beads(source))

    with caplog.at_level(logging.INFO):
        asyncio.run(_clicked_twice(leg, source, caplog))

    lines = [r.getMessage() for r in caplog.records if "click beads:" in r.getMessage()]
    stood_down = next(line for line in lines if "stood down" in line)
    assert "a load was already running" in stood_down
    assert "answered" in stood_down  # its own answer, timed as every click's is
    assert "fetched" not in stood_down  # and no figure for the query it skipped
    assert any("fetched" in line for line in lines)  # which the other click reports


def test_a_click_that_could_not_be_started_is_reported_rather_than_lost(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A click is a task nobody waits on, so nothing else can report its failure.

    An exception escaping the coroutine would sit unread in a task, and go out —
    if it went anywhere at all — as an unretrieved-exception warning from the
    loop, after the click it belonged to had been forgotten.
    """
    _patch_rest(monkeypatch, _RefusingClient())
    leg = AppletLeg(_IDENTITY, _OrderedService())

    def _no_worker(func: object, /, *args: object, **kwargs: object) -> None:
        raise RuntimeError("no worker thread could be started")

    monkeypatch.setattr("punt_lux.applets.runner.asyncio.to_thread", _no_worker)

    with caplog.at_level(logging.ERROR):
        asyncio.run(_clicked(leg))  # draining re-raises anything the task let out

    assert "a click could not be serviced at all" in caplog.text
    assert "no worker thread could be started" in caplog.text
