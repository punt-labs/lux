"""Which board the applet keeps, and which board the user ends up looking at.

The partitions here are the ones named in ``docs/board_ordering_coverage.md``,
against the model in ``docs/board_ordering.tex``. The model's five properties are
that the slot never goes backwards, the display never goes backwards, at rest the
display shows the newest board anybody pushed, the display never runs ahead of the
slot, and the display never shows a board the slot refused.

Every test drives the real service, the real slot and the real push region. What
is stubbed is ``bd`` and the Hub — a source that hands out prepared results, and a
client that can be stopped inside a round trip. Stopping inside the round trip is
the whole point: each of these properties is about what another thread does while
a push is in flight, so a test that let the push complete instantly would exercise
the premise rather than the mechanism.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Self, final

import punt_lux.applets as applets_package
from punt_lux.applets.applet_board import AppletBoard
from punt_lux.applets.beads_service import BeadsService
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_slot import BoardSlot
from punt_lux.applets.board_work import BoardWork
from punt_lux.applets.latency import ClickLatency
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsFailure, BeadsRows
from punt_lux.operations.models.scene_results import SceneShown

from .board_doubles import GATE_SECONDS, ISSUE, Gated, loaded

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.apps.beads_load import BeadsLoad
    from punt_lux.apps.beads_result import BeadsResult
    from punt_lux.operations import RenderRequest, RenderTableRequest

# Two boards a test can tell apart on sight, so the id that landed says which of
# two overlapping loads the display ended up showing.
_STALE = BeadsRows.of([ISSUE | {"id": "lux-stale"}])
_FRESH = BeadsRows.of([ISSUE | {"id": "lux-fresh"}])
_STALE_ID = "lux-stale"
_FRESH_ID = "lux-fresh"

# The two things that are not a board: the placeholder a cold click opens on, and
# the red message naming why ``bd`` could not be read.
_LOADING = "loading"
_FAILURE = "failure"

# How long a test waits on another thread to reach a state it must reach. A
# machine under load takes longer than a free one; a thread that is never getting
# there fails the run rather than holding it.
_SETTLE_SECONDS = 5.0


class Crossing(Protocol):
    """A point in a round trip a thread may be stopped at."""

    def cross(self) -> None:
        """Pass through, once whoever is holding this open lets go."""
        ...


@final
class OpenGate:
    """A point nobody is stopped at — the ordinary round trip."""

    __slots__ = ()

    def cross(self) -> None:
        """Pass straight through."""


# The default for both gates: a client that stops nowhere. It holds no state, so
# every client that wants an ordinary round trip can share this one.
_OPEN: Crossing = OpenGate()


@final
class Gate:
    """A place the first thread through is stopped, and later ones are not.

    The push region admits one writer at a time, so a test that needs a second
    writer to arrive during the first one's write has to stop that first write
    and nothing else. Later arrivals pass straight through.
    """

    _crossed: bool
    _lock: threading.Lock
    _reached: threading.Event
    _released: threading.Event
    __slots__ = ("_crossed", "_lock", "_reached", "_released")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._crossed = False
        self._lock = threading.Lock()
        self._reached = threading.Event()
        self._released = threading.Event()
        return self

    def cross(self) -> None:
        """Stop here the first time anyone arrives; let everyone else by."""
        with self._lock:
            if self._crossed:
                return
            self._crossed = True
        self._reached.set()
        self._released.wait(timeout=GATE_SECONDS)

    def reached(self) -> None:
        """Block until a thread is standing at this gate."""
        assert self._reached.wait(timeout=GATE_SECONDS), "nothing reached the gate"

    def release(self) -> None:
        """Let the thread standing here finish what it was doing."""
        self._released.set()


@final
class InTurn:
    """A source handing out one prepared result per load, in the order given.

    Two loads of the same board are two different boards here, which is what
    makes an ordering assertion possible at all: the id that landed says which
    load produced what the user is looking at.
    """

    _loads: int
    _lock: threading.Lock
    _results: list[BeadsResult]
    __slots__ = ("_loads", "_lock", "_results")

    def __new__(cls, *results: BeadsResult) -> Self:
        self = super().__new__(cls)
        self._results = list(results)
        self._loads = 0
        self._lock = threading.Lock()
        return self

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        """Answer the next prepared result; repeat the last one after that."""
        with self._lock:
            taken = min(self._loads, len(self._results) - 1)
            self._loads += 1
        return loaded(self._results[taken])


@final
class Landings:
    """What reached the display, in the order it landed there.

    Two clients can write to one display, and what the user ends up looking at
    is not settled by either client's call order — it is settled by the order the
    writes landed. Both write here, so the sequence is one sequence.
    """

    _lock: threading.Lock
    _shown: list[str]
    __slots__ = ("_lock", "_shown")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._shown = []
        return self

    def landed(self, what: str) -> None:
        """Record that *what* is now on the display."""
        with self._lock:
            self._shown.append(what)

    @property
    def shown(self) -> tuple[str, ...]:
        """Everything that landed, in the order it landed."""
        with self._lock:
            return tuple(self._shown)

    @property
    def last(self) -> str:
        """What the display ended up showing."""
        return self.shown[-1]


@final
class SteppedClient:
    """A client that can be stopped inside a raise or inside a push.

    Every property here is about what happens *during* a round trip, so a round
    trip is where a test has to be able to stand. Which of the two is gated is
    which race the test is about: a raise that hangs is a click that has read the
    applet's state and not yet shown anything, and a push that hangs is a write
    in flight with the display not yet changed.
    """

    _landings: Landings
    _pushes: Crossing
    __slots__ = ("_landings", "_pushes")

    def __new__(
        cls,
        landings: Landings,
        *,
        pushes: Crossing = _OPEN,
    ) -> Self:
        self = super().__new__(cls)
        self._landings = landings
        self._pushes = pushes
        return self

    def render_table(self, request: RenderTableRequest) -> SceneShown:
        """Land a board, after however long this client's write is made to take."""
        self._pushes.cross()
        self._landings.landed(str(request.rows[0][0]) if request.rows else "empty")
        return SceneShown(scene_id=request.scene_id)

    def render(self, request: RenderRequest) -> SceneShown:
        """Land what is not a board: the placeholder, or the reason there is none."""
        self._pushes.cross()
        text = str(request.elements)
        self._landings.landed(_LOADING if "Loading issues" in text else _FAILURE)
        return SceneShown(scene_id=request.scene_id)


@final
class Applet:
    """A Beads service with its slot in the open, so a test can see both ends.

    What the applet holds and what the display shows are two different things,
    and every property here is a statement about the pair. The slot is handed to
    the service rather than made by it, so a test holding the same slot can ask
    what the applet is holding at any moment — including from inside a push.
    """

    _service: BeadsService
    _slot: BoardSlot
    _spare: BoardWork
    _spare_landings: Landings
    __slots__ = ("_service", "_slot", "_spare", "_spare_landings")

    def __new__(cls, source: object) -> Self:
        self = super().__new__(cls)
        load = BoardLoad(BeadsBoard.for_project("lux"), source)  # type: ignore[arg-type]  # structural stand-in
        self._slot = BoardSlot()
        self._service = BeadsService(AppletBoard(load, self._slot))
        # A click nobody made, against a display nobody is looking at: pushing
        # the slot's state into it is how a test reads what the applet holds.
        self._spare_landings = Landings()
        self._spare = BoardWork(
            load,
            SteppedClient(self._spare_landings),  # type: ignore[arg-type]  # structural stand-in
            ClickLatency("beads"),
        )
        return self

    def prefetch(self) -> None:
        """Run the warm-up: it loads and stores, and shows nothing."""
        self._service.prefetch()

    def answer(self, client: object) -> ClickLatency:
        """Give a click its visible answer, timed as the leg times it."""
        latency = ClickLatency("beads")
        with latency.answering():
            self._service.acknowledge(client, latency)  # type: ignore[arg-type]  # structural stand-in
        return latency

    def service(self, client: object) -> None:
        """Run a click's slow half: load, store, and show what is held."""
        self._service.service(client, ClickLatency("beads"))  # type: ignore[arg-type]  # structural stand-in

    def click(self, client: object) -> None:
        """Drive both halves of a click, exactly as the leg drives them."""
        latency = self.answer(client)
        self._service.service(client, latency)  # type: ignore[arg-type]  # structural stand-in

    def holds(self) -> str:
        """What the applet is holding, named as a landing on the display is."""
        self._slot.held.shows(self._spare)
        return self._spare_landings.last


def _until(ready: Callable[[], bool], what: str) -> None:
    """Wait for another thread to have *what*, or fail rather than hang."""
    deadline = time.monotonic() + _SETTLE_SECONDS
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(0.001)
    raise AssertionError(f"the other thread never {what}")


def _thread(work: Callable[[], object]) -> threading.Thread:
    """A started thread running *work* — the second writer a test needs."""
    running = threading.Thread(target=work)
    running.start()
    return running


def _joined(*threads: threading.Thread) -> None:
    """Wait for every thread, and fail rather than leave one running."""
    for running in threads:
        running.join(timeout=GATE_SECONDS)
        assert not running.is_alive(), "a thread never finished"


def _applet_sources() -> dict[str, str]:
    """Every module of the applets package, by file name."""
    root = Path(next(iter(applets_package.__path__)))
    return {path.name: path.read_text(encoding="utf-8") for path in root.glob("*.py")}


def _writers(source: str) -> set[str]:
    """The methods of this module that write the display through a click's work."""
    return {
        method.name
        for method in ast.walk(ast.parse(source))
        if isinstance(method, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "push"
            for call in ast.walk(method)
        )
    }


def _tells_a_state_to_show(source: str) -> bool:
    """Whether this module tells a state to put itself on the display.

    A state is told with one argument, the click's work; the region is *entered*
    with two, the work and what the caller would have shown. Counting arguments
    is what tells the two apart without naming either caller.
    """
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "shows"
        and len(call.args) == 1
        for call in ast.walk(ast.parse(source))
    )


def _imports(source: str) -> set[str]:
    """Every module a source file imports, whether or not the import is deferred.

    Prose about another module is not a dependency on it; an import is. The
    slot's docstring names the region because it states the acquisition order,
    so the question this answers has to be asked of the code.
    """
    named: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            named.add(node.module)
        elif isinstance(node, ast.Import):
            named.update(alias.name for alias in node.names)
    return named


# --- P1 -------------------------------------------------------------------


def test_two_pushes_land_in_the_order_they_were_taken() -> None:
    """The display must end at the newer board however the two writes overlap.

    Two workers push, and the first one's write is held open while the second
    arrives with a newer board. Left unordered, the two land in whichever order
    the sockets finish in, and the older board can be the one left on screen —
    the defect four review rounds kept finding. The region admits one writer at
    a time and holds its lock across the write, so the second lands second.
    """
    landings = Landings()
    pushes = Gate()
    applet = Applet(InTurn(_STALE, _FRESH))
    applet.prefetch()  # the applet is holding the older board

    answering = _thread(lambda: applet.answer(SteppedClient(landings, pushes=pushes)))
    pushes.reached()  # the first write is in flight and cannot yet have landed
    refreshing = _thread(lambda: applet.service(SteppedClient(landings)))
    _until(lambda: applet.holds() == _FRESH_ID, "stored the newer board")
    pushes.release()
    _joined(answering, refreshing)

    assert landings.shown == (_STALE_ID, _FRESH_ID)
    assert landings.last == _FRESH_ID


# --- P2 -------------------------------------------------------------------

# P2's own scenario -- a click's acknowledge observes the slot, then a refresh
# on another thread stores and shows a newer board, then the first click
# reaches its push -- described an interleaving that ran *inside the raise
# round trip*: the raise was the only I/O between "observe" and "push" a test
# could gate. lux-81t3.5 (DES-088) removed that round trip: acknowledge no
# longer performs any I/O between reading the slot and calling
# BoardGlass.shows, which itself re-reads the slot fresh, under its own lock,
# immediately before every push (see BoardGlass.shows's docstring). There is
# no longer a gateable point between "observe" and "push" on the click's own
# thread, so this partition of the interleaving space is no longer
# constructible -- not merely untested, structurally absent. The invariant it
# protected (I2: the display never shows what a pusher captured before a
# newer board landed) still holds, now by construction, and the interleaving
# that remains reachable -- two writers both inside BoardGlass's lock -- is
# P1's test above.


# --- P3 -------------------------------------------------------------------

# P3's scenario gated a stood-down click's *acknowledge* phase at its raise, so
# a refresh could land a newer board while the stood-down click still held an
# older one it had read. Like P2, that gate is gone: acknowledge does no I/O
# now, so a click's one push (made during acknowledge, before it stands down
# or not) always carries what BoardGlass reads fresh at that instant --
# there is no captured board left for a later, un-gateable stand-down to push
# stale. See P2's note above; the same elimination applies here.


# --- P4 -------------------------------------------------------------------


def test_a_refresh_stores_its_board_before_it_shows_it() -> None:
    """The display must never hold a board the applet does not.

    One worker and no race at all: the load returns, and the board is stored
    before the write carrying it begins. Pushing first leaves the screen showing
    issues the applet has not kept for the whole length of the round trip — and
    shows them before the slot has had its chance to refuse them.
    """
    landings = Landings()
    pushes = Gate()
    applet = Applet(InTurn(_FRESH))

    refreshing = _thread(lambda: applet.service(SteppedClient(landings, pushes=pushes)))
    pushes.reached()  # the write is in flight, so the store has already happened

    assert applet.holds() == _FRESH_ID

    pushes.release()
    _joined(refreshing)
    assert landings.shown == (_FRESH_ID,)


# --- P5 -------------------------------------------------------------------


def test_a_board_the_slot_refused_never_reaches_the_display() -> None:
    """A board the applet threw away must not be what the user is looking at.

    A click's query begins, a reconnect fires the warm-up, and the warm-up's
    query begins later and returns first. The click's board is therefore the
    older one and the slot refuses it — so it must not have been put on screen
    on the way, which is exactly what a push taken before the store does.
    """
    landings = Landings()
    source = Gated(_FRESH, gated=_STALE)  # the click's load begins first, returns last
    applet = Applet(source)

    clicking = _thread(lambda: applet.service(SteppedClient(landings)))
    source.reached()  # the click's query is in flight
    applet.prefetch()  # the warm-up begins later, returns first, and stores
    source.release()  # and only now does the click's older board come back
    _joined(clicking)

    assert applet.holds() == _FRESH_ID
    assert landings.shown == (_FRESH_ID,)
    assert _STALE_ID not in landings.shown


# --- P6 -------------------------------------------------------------------

# P6's scenario gated the placeholder-pushing click at its raise, so a board
# could arrive and be shown while the cold click's own round trip was still in
# flight, then have the placeholder land over it once released. The raise is
# gone (same elimination as P2), and the placeholder is now pushed
# immediately, inside BoardGlass's lock, with no I/O beforehand -- there is no
# window left in which a board could arrive between "the click decided to
# offer the placeholder" and "the placeholder is offered." Offered rather than
# pushed still means BoardGlass.shows's newer_of always wins for whichever
# board actually reaches the slot first; P1 and P4 exercise that ordering.
#
# Reconsidered for round 2 (lux-81t3.5): could P6 still be constructed by
# gating on `pushes` -- the socket write itself, inside BoardGlass._lock --
# rather than the deleted `raises` gate? No, and the reason is the region's
# own lock discipline, not the raise: BoardGlass._lock fully serialises every
# call to `shows`, read-then-write, so at most one push is ever in flight.
# For P6 to hold, a board's own `shows` call would have to complete and land
# BEFORE the placeholder's `shows` call reads the slot -- but a completed push
# can only be observed by a later reader (the lock guarantees it), so a
# placeholder-click that reads an empty slot proves no board's push has
# landed yet, and any push still holding the lock blocks every other caller,
# including a real board's, until it releases. A store landing mid-push (via
# BoardSlot.store, which does not take this lock) cannot retroactively change
# what a push already in flight sends -- that is exactly the gap P12 measures
# and names as accepted staleness, not a P6-shaped violation: gating `pushes`
# this way reconstructs P12's scenario
# (test_a_store_landing_during_a_push_leaves_the_display_one_behind, which
# proves the earlier-decided value lands and the later store does not
# retroactively pre-empt it), not a new one. P6 is therefore unconstructable
# for a distinct, stronger reason than P2/P3 (which lost their gateable point
# entirely): here the gateable point still exists, but the lock's
# full-serialisation and fresh-read-at-decision-time design prove no
# ordering it permits can ever blank an already-landed board.


# --- P7 -------------------------------------------------------------------


def test_the_first_placeholder_of_a_session_still_appears() -> None:
    """The cold click must still say what it is doing, or the menu looks broken.

    The boundary partner of the partition above, and the one that rules out
    fixing it with a counter: a rule that only pushed something newer than the
    last push could never admit the first placeholder at all.
    """
    landings = Landings()
    applet = Applet(InTurn(_FRESH))

    applet.answer(SteppedClient(landings))

    assert landings.shown == (_LOADING,)


# --- P8 -------------------------------------------------------------------


def test_the_failure_message_never_lands_over_a_board() -> None:
    """A red message where a readable board is showing is the worse answer.

    The click's ``bd`` fails while a warm-up's board arrives and is shown. The
    reason is held by the state the load hands back rather than pushed on the
    spot, so putting it up is the same act as putting a board up — and inside
    the region the board the applet is holding wins.
    """
    landings = Landings()
    source = Gated(_FRESH)  # the first load hangs and then fails; later ones succeed
    applet = Applet(source)

    clicking = _thread(lambda: applet.service(SteppedClient(landings)))
    source.reached()  # the click's query is in flight and about to fail
    applet.service(SteppedClient(landings))  # a board arrives and goes up
    source.release()
    _joined(clicking)

    assert _FAILURE not in landings.shown
    assert landings.last == _FRESH_ID


# --- P9 -------------------------------------------------------------------


def test_the_failure_message_appears_when_there_is_nothing_to_lose() -> None:
    """Every way a read can fail has to become something the user can see.

    The boundary partner of the partition above: the guard that keeps a message
    off a board must not become "never show the reason at all".
    """
    landings = Landings()
    applet = Applet(InTurn(BeadsFailure("bd: connection refused")))

    applet.click(SteppedClient(landings))

    assert landings.shown == (_LOADING, _FAILURE)


# --- P10 ------------------------------------------------------------------


def test_the_slot_keeps_the_board_whose_load_began_last() -> None:
    """The rule the display half is built on must not regress while it changes.

    Which writer stored last does not decide it; which load began last does. The
    warm-up here begins first and returns last, so its issues are the older ones
    however late its board arrives. ``tests/applets/test_board_slot.py`` drives
    the slot's own contention; this pins the same rule through the service, with
    the display asserted beside it.
    """
    landings = Landings()
    source = Gated(_FRESH, gated=_STALE)  # the warm-up begins first, returns last
    applet = Applet(source)

    warming = _thread(applet.prefetch)
    source.reached()  # the warm-up's query is in flight
    applet.service(SteppedClient(landings))  # a later query returns first and stores
    source.release()  # and only now does the warm-up return, with older issues
    _joined(warming)

    assert applet.holds() == _FRESH_ID
    assert landings.shown == (_FRESH_ID,)


# --- P11 ------------------------------------------------------------------


def test_nothing_writes_the_display_from_outside_the_push_region() -> None:
    """The lock discipline, checked where a runtime test would only hang.

    Two obligations hold this design up and neither can be asserted by running
    it without a test that wedges when it fails. The first is that every push
    goes through the region: the only caller of a click's write is the region
    itself, and the region holds its lock across it. The second is the
    acquisition order — the region's lock is the outer one, so the slot must
    never reach for it, and one direction is not a cycle.
    """
    sources = _applet_sources()

    # A state writes the display in one method and nowhere else, so telling one
    # to show itself is the only way anything reaches the glass. The write's own
    # definition is the third module here, and it is a definition, not a caller.
    for state in ("held_board.py", "no_board.py"):
        assert _writers(sources[state]) == {"shows"}, f"{state} writes elsewhere"
    assert _writers(sources["board_work.py"]) == {"push"}
    writing = {name for name, text in sources.items() if _writers(text)}
    assert writing == {"board_work.py", "held_board.py", "no_board.py"}

    # And only the region tells one to, holding its lock while it does.
    telling = {name for name, text in sources.items() if _tells_a_state_to_show(text)}
    assert telling == {"board_glass.py"}, "a state was shown outside the region"
    region = sources["board_glass.py"]
    assert region.index("with self._lock:") < region.index(".shows(work)"), (
        "the region's lock is not held across the write"
    )

    slot = sources["board_slot.py"]
    assert _imports(slot).isdisjoint({"punt_lux.applets.board_glass"}), (
        "the slot can reach the region's lock"
    )
    assert slot.count("threading.Lock()") == 1


# --- P12 ------------------------------------------------------------------


def test_a_store_landing_during_a_push_leaves_the_display_one_behind() -> None:
    """The boundary this design does not close, put as the weaker true thing.

    The slot's lock is not held across the write — the write is a socket round
    trip — so a board stored between the read and the write is held and not yet
    shown. That is ordinary staleness: the display is *behind* the slot, which
    breaks nothing, rather than ahead of it or showing something refused. It is
    also what proves the two locks are not one: the store completes while the
    write is still in flight.
    """
    landings = Landings()
    pushes = Gate()
    applet = Applet(InTurn(_STALE, _FRESH))
    applet.prefetch()

    answering = _thread(lambda: applet.answer(SteppedClient(landings, pushes=pushes)))
    pushes.reached()  # the write has read the slot and is in flight
    applet.prefetch()  # a newer board is stored while it is
    pushes.release()
    _joined(answering)

    assert landings.shown == (_STALE_ID,)  # one generation behind, and not ahead
    assert applet.holds() == _FRESH_ID
