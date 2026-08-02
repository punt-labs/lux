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
import threading

import pytest

from punt_lux.applets.beads_service import BeadsService
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.latency import ClickLatency
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsFailure, BeadsRows

from .board_doubles import (
    GATE_SECONDS,
    ISSUE,
    Gated,
    Journal,
    RecordingClient,
    Source,
    ThenFails,
    UnraisableClient,
)

# Two boards a test can tell apart on sight, so that the id a later click
# answers with says which of two overlapping loads the applet kept.
_STALE = ISSUE | {"id": "lux-stale"}
_FRESH = ISSUE | {"id": "lux-fresh"}


def _service(source: Source | ThenFails | Gated) -> BeadsService:
    return BeadsService(BoardLoad(BeadsBoard.for_project("lux"), source))


def _click(service: BeadsService, client: object) -> ClickLatency:
    """Service one click and return the clock it was timed on.

    The stand-in clients are structural, so the one cast the tests need lives
    here rather than on every call.
    """
    latency = ClickLatency("beads")
    service.service(client, latency)  # type: ignore[arg-type]  # structural stand-in
    return latency


def _answer(service: BeadsService, client: object) -> ClickLatency:
    """Drive only the half of a click the user sees, timed as the leg times it.

    The answer is timed by the leg rather than by the service, so the helper
    wraps it here too — a click whose answer went untimed would report a line no
    real click can produce.
    """
    latency = ClickLatency("beads")
    with latency.answering():
        service.acknowledge(client, latency)  # type: ignore[arg-type]  # structural stand-in
    return latency


def _whole_click(service: BeadsService, client: object) -> ClickLatency:
    """Drive both halves of a click exactly as the leg drives them."""
    latency = _answer(service, client)
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
    client = RecordingClient()
    _click(_service(Source(BeadsRows.of([ISSUE]))), client)

    assert len(client.tables) == 1
    assert client.scenes == []
    table = client.tables[0]
    assert table.scene_id == "beads-lux"  # the repository's one board
    assert table.frame_id == "beads-lux"
    assert [row[0] for row in table.rows] == ["lux-1"]


def test_a_bd_failure_renders_the_reason_in_the_window() -> None:
    client = RecordingClient()
    _click(_service(Source(BeadsFailure("bd: command not found"))), client)

    assert client.tables == []
    assert len(client.scenes) == 1
    assert "bd: command not found" in str(client.scenes[0].elements)


def test_an_empty_board_still_renders() -> None:
    client = RecordingClient()
    _click(_service(Source(BeadsRows.of([]))), client)

    assert len(client.scenes) == 1
    assert "No active issues." in str(client.scenes[0].elements)


def test_an_unforeseen_failure_renders_rather_than_vanishing() -> None:
    """A click that produces nothing visible reads to the user as a broken menu."""
    client = RecordingClient()
    _click(_service(Source(raises=True)), client)

    assert len(client.scenes) == 1
    assert "could not be built" in str(client.scenes[0].elements)


def test_a_refused_render_is_reported_not_raised() -> None:
    """The servicing thread survives a Hub refusal; there is nowhere to render it."""
    client = RecordingClient(refuse=True)
    _click(_service(Source(BeadsRows.of([ISSUE]))), client)

    assert len(client.tables) == 1  # the attempt happened and did not raise


def test_the_stages_behind_the_answer_are_timed_one_by_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A board that took a while has to name which of its stages took it.

    The query goes to a hosted database, the build is local, and the push is a
    round trip to luxd — three different problems wearing one wait. Timing them
    separately is what turns "it took a while" into which of the three it was.
    """
    client = RecordingClient()
    latency = _click(_service(Source(BeadsRows.of([ISSUE]))), client)

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
    client = RecordingClient()
    latency = _click(_service(Source(BeadsRows.of([ISSUE]))), client)

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
    client = RecordingClient(frame_is_up=False)
    service = _service(Source(BeadsRows.of([ISSUE])))

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
    client = RecordingClient()
    latency = _click(_service(Source(raises=True)), client)

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
    journal = Journal()
    client = RecordingClient(journal=journal, frame_is_up=True)
    service = _service(Source(BeadsRows.of([ISSUE]), journal=journal))

    _whole_click(service, client)

    assert journal.steps == ("raise", "load", "render_table")
    assert client.scenes == []  # a board that is up needs no placeholder


def test_a_click_with_no_board_up_opens_one_before_asking_bd_anything() -> None:
    """The cold click: there is no frame to raise, so one is put up immediately."""
    journal = Journal()
    client = RecordingClient(journal=journal, frame_is_up=False)
    service = _service(Source(BeadsRows.of([ISSUE]), journal=journal))

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
    journal = Journal()
    client = UnraisableClient(journal)
    service = _service(Source(BeadsRows.of([ISSUE]), journal=journal))

    _whole_click(service, client)

    assert journal.steps == ("raise", "load", "render_table")


def test_a_prefetched_board_is_shown_before_the_fresh_load_begins() -> None:
    """The click the whole warm-up is for: the answer is a board, not a word.

    A cold click opens "Loading issues…" and the user reads it for as long as the
    query takes — measured at ~4.9 s against the hosted database. With a board
    already loaded there is something real to put up instead, and it goes up
    before the fresh query starts rather than after it returns.
    """
    journal = Journal()
    client = RecordingClient(journal=journal, frame_is_up=False)
    service = _service(Source(BeadsRows.of([ISSUE]), journal=journal))

    service.prefetch()
    _whole_click(service, client)

    # The board is pushed between the raise and the click's own load — the two
    # facts that make it an answer rather than a result.
    assert journal.steps == ("load", "raise", "render_table", "load", "render_table")
    assert client.scenes == []  # and no placeholder was shown at any point


def test_a_click_pushes_the_board_it_holds_onto_a_frame_already_up() -> None:
    """A frame that is up is not a promise about what is in it.

    The board is kept whatever became of the push behind it — the query has been
    paid for either way — so a push the Hub refused leaves the applet holding
    issues the screen never got, with the frame still standing over the older
    ones. A click that stopped at the raise would bring that older board forward
    and keep the newer one to itself, and so would every click after it: the
    screen would never catch up. The held board therefore goes up whatever the
    raise answered.
    """
    service = _service(Source(BeadsRows.of([ISSUE])))
    _whole_click(service, RecordingClient(refuse=True, frame_is_up=False))

    client = RecordingClient(frame_is_up=True)
    _answer(service, client)

    assert len(client.tables) == 1  # the answer was the board, not the raise alone
    assert [row[0] for row in client.tables[0].rows] == ["lux-1"]
    assert client.scenes == []


def test_a_raise_that_cannot_be_answered_still_shows_the_board_held() -> None:
    """A failed round trip must not cost the click the board it already had.

    The raise can fail while the display is perfectly alive — a timed-out trip,
    a display that came up after luxd. Reading that as "the board is up" and
    stopping there hands the user a click that did nothing visible and then
    makes them wait out the whole query anyway, which is the one wait the held
    board exists to spare them.
    """
    journal = Journal()
    client = UnraisableClient(journal)
    service = _service(Source(BeadsRows.of([ISSUE]), journal=journal))

    service.prefetch()
    _whole_click(service, client)

    # The cached push sits between the raise and the click's own load: it is the
    # answer, not the result.
    assert journal.steps == ("load", "raise", "render_table", "load", "render_table")


@pytest.mark.parametrize(
    ("prefetched", "frame_is_up", "said"),
    [
        (True, False, "cached board"),
        (True, True, "cached board"),
        (False, True, "frame already up"),
        (False, False, "loading placeholder"),
    ],
)
def test_the_line_says_which_of_its_answers_the_click_gave(
    caplog: pytest.LogCaptureFixture,
    *,
    prefetched: bool,
    frame_is_up: bool,
    said: str,
) -> None:
    """Every answer a click can give is fast; only the line tells them apart.

    Pushing a board the applet already had, pushing "Loading issues…", and
    finding a frame up with nothing better to put in it are all a few
    milliseconds, so the figure is the same and what the user got is not. The
    line names what was pushed — and it has to keep naming it, because a click
    that reported a cached board while pushing nothing would hide exactly the
    case where the screen and the applet disagree.
    """
    client = RecordingClient(frame_is_up=frame_is_up)
    service = _service(Source(BeadsRows.of([ISSUE])))
    if prefetched:
        service.prefetch()

    latency = _answer(service, client)
    with caplog.at_level(logging.INFO):
        latency.report()

    assert f"({said})" in _reported(caplog)


def test_a_click_says_when_its_answer_was_a_board_it_already_had(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two clicks with the same figures are not the same click.

    Answering in 28 ms with the board reads differently from answering in 28 ms
    with the word "Loading", and the load behind them is a wait in one case and
    not in the other. The line says which, and times the load as one figure
    because no stage of it is the user's problem.
    """
    client = RecordingClient(frame_is_up=False)
    service = _service(Source(BeadsRows.of([ISSUE])))

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
    journal = Journal()
    client = RecordingClient(journal=journal, frame_is_up=False)
    service = _service(ThenFails(BeadsRows.of([ISSUE]), journal))

    service.prefetch()
    with caplog.at_level(logging.WARNING):
        _whole_click(service, client)

    assert client.scenes == []  # no red message replaced the board
    assert len(client.tables) == 1  # only the answer was pushed; nothing after it
    assert "the one on screen stands" in caplog.text
    assert "bd: connection refused" in caplog.text


def test_a_board_that_arrives_mid_click_outlives_the_click_that_failed() -> None:
    """A click failing while the warm-up lands must not cost the board it landed.

    The first click of a session can arrive before the warm-up has finished: the
    entry is registered as soon as the Hub accepts it, and the load behind it
    runs on another thread, so an early click is the intended path rather than an
    edge. That click reads the applet's state — nothing yet — runs its own load,
    and its ``bd`` can fail while the warm-up's board is landing. What it holds
    afterwards is nothing, and writing that back over the arrived board would
    make the next click pay the whole query again.
    """
    source = Gated(BeadsRows.of([ISSUE]))
    service = _service(source)
    failing = RecordingClient(frame_is_up=False)
    click = threading.Thread(
        target=service.service, args=(failing, ClickLatency("beads"))
    )

    click.start()
    source.reached()  # the click has read the state and its load is in flight
    service.prefetch()  # the warm-up's board lands behind it
    source.release()  # and only now does the click's load fail
    click.join(timeout=GATE_SECONDS)

    assert not click.is_alive()
    assert "connection refused" in str(failing.scenes[0].elements)  # the click failed

    # And the next click answers with the board that arrived, not a placeholder.
    answering = RecordingClient(frame_is_up=False)
    _answer(service, answering)
    assert len(answering.tables) == 1
    assert answering.scenes == []


def test_the_board_from_the_load_that_began_last_is_the_one_kept() -> None:
    """A warm-up that began before a click must not displace the click's board.

    A board's issues are as old as the query that read them, and that query's
    snapshot is fixed when it starts. So the warm-up here holds the older issues
    even though it returns last: it began first. Deciding between the two by
    which returned last would put the stale board back and hold it there until
    somebody clicked again.
    """
    source = Gated(BeadsRows.of([_FRESH]), gated=BeadsRows.of([_STALE]))
    service = _service(source)
    warm = threading.Thread(target=service.prefetch)

    warm.start()
    source.reached()  # the warm-up's query began first and is in flight
    _click(service, RecordingClient(frame_is_up=False))  # a later query returns first
    source.release()  # and only now does the warm-up return, with older issues
    warm.join(timeout=GATE_SECONDS)

    assert not warm.is_alive()

    # The next click answers with the issues read last, not the board stored last.
    answering = RecordingClient(frame_is_up=False)
    _answer(service, answering)
    assert [row[0] for row in answering.tables[0].rows] == ["lux-fresh"]


def test_a_board_that_could_not_be_prefetched_leaves_the_click_cold(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed warm-up holds nothing: the next click must not answer with it."""
    journal = Journal()
    client = RecordingClient(journal=journal, frame_is_up=False)
    service = _service(Source(BeadsFailure("bd: command not found"), journal=journal))

    with caplog.at_level(logging.WARNING):
        service.prefetch()
    _whole_click(service, client)

    assert "ahead of the first click" in caplog.text
    assert journal.steps == ("load", "raise", "render", "load", "render")
    assert "Loading issues" in str(client.scenes[0].elements)  # the cold answer
    assert "bd: command not found" in str(client.scenes[1].elements)
