"""SessionCallbackLeg — servicing a click without starving the leg's own lease.

The leg's loop does two things: it renews the session's lease, and it receives
clicks. The work a click asks for blocks — ``bd`` runs to its own timeout, the
board push is HTTP — so it must not run on that loop. If it did, a slow click
would stall the renewal until the lease lapsed, and the session's menu entry
would disappear mid-service.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.operations import OpError
from punt_lux.rest_transport import HubUnavailableError
from punt_lux.session_service import SessionCallbackLeg

if TYPE_CHECKING:
    import pytest

    from punt_lux.rest_client import LuxRestClient

_IDENTITY = ClientIdentity(kind="mcp-session", name="lux · lux · #1", repo="/w/lux")


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

    def service(self, client: LuxRestClient) -> None:
        self._started.set()
        self._release.wait(timeout=5)
        self._serviced += 1

    @property
    def serviced(self) -> int:
        return self._serviced


@final
class _RefusingClient:
    """A REST client stand-in whose registration is refused."""

    __slots__ = ()

    def register_callback(self, callback_id: str, label: str) -> OpError:
        return OpError(code="push_required", reason="no listen leg")


def _patch_rest(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    """Point the leg's per-use REST client at a stand-in, not a running Hub."""

    def _for_identity(_identity: ClientIdentity, *, timeout: float = 2.0) -> object:
        return client

    monkeypatch.setattr(
        "punt_lux.session_service.LuxRestClient.for_identity", _for_identity
    )


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
    leg = SessionCallbackLeg(_IDENTITY, service)

    async def _drive() -> int:
        ticks = 0
        click = asyncio.create_task(leg._on_callback("beads"))
        await asyncio.to_thread(started.wait, 5)  # the work has begun and blocked
        for _ in range(5):  # the loop keeps running while the work blocks
            await asyncio.sleep(0)
            ticks += 1
        # The assertion that makes this bite: the work is STILL blocked, and the
        # loop advanced anyway. Counting ticks alone proves nothing — work that
        # ran on the loop would simply finish first and let them run afterwards.
        assert service.serviced == 0
        release.set()
        await click
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
    leg = SessionCallbackLeg(_IDENTITY, service)

    with caplog.at_level(logging.WARNING):
        asyncio.run(leg._on_callback("something-else"))

    assert service.serviced == 0
    assert "no service for callback" in caplog.text


def test_a_refused_registration_is_reported_and_the_session_continues(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed register must not raise: the listen leg has to stay up either way."""
    started, release = threading.Event(), threading.Event()
    _patch_rest(monkeypatch, _RefusingClient())
    leg = SessionCallbackLeg(_IDENTITY, _SlowService(started, release))

    with caplog.at_level(logging.ERROR):
        asyncio.run(leg._register())

    assert "menu entry was refused" in caplog.text


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

    def service(self, client: LuxRestClient) -> None:
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

    def service(self, client: LuxRestClient) -> None:
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
    leg = SessionCallbackLeg(_IDENTITY, _PushingService())

    with caplog.at_level(logging.WARNING):
        asyncio.run(leg._on_callback("beads"))  # must not raise

    assert "rendered nothing" in caplog.text
    assert "the read timed out" in caplog.text  # not "luxd is not running yet"


def test_a_hub_that_vanishes_before_the_client_is_built_leaves_the_leg_up(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Building the client reads luxd's port, so `make restart` lands here too."""

    def _unreachable(_identity: ClientIdentity, *, timeout: float = 2.0) -> object:
        raise HubUnavailableError("luxd is not running")

    monkeypatch.setattr(
        "punt_lux.session_service.LuxRestClient.for_identity", _unreachable
    )
    started, release = threading.Event(), threading.Event()
    release.set()
    leg = SessionCallbackLeg(_IDENTITY, _SlowService(started, release))

    with caplog.at_level(logging.WARNING):
        asyncio.run(leg._on_callback("beads"))  # must not raise

    assert "unreachable" in caplog.text
    assert "rendered nothing" in caplog.text


def test_an_unforeseen_servicing_failure_does_not_tear_the_socket(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Anything at all going wrong in a click is survivable; the leg is not."""
    _patch_rest(monkeypatch, _UnreachableHub())
    leg = SessionCallbackLeg(_IDENTITY, _ExplodingService())

    with caplog.at_level(logging.ERROR):
        asyncio.run(leg._on_callback("beads"))  # must not raise

    assert "servicing a click failed" in caplog.text
    assert "the leg stays up" in caplog.text
