"""End-to-end: a session's leg registers itself and services a click with no turn.

Runs the real assembled luxd app on an ephemeral loopback port and starts the
shipped :class:`SessionCallbackLeg` against it, exactly as ``lux mcp-serve`` does.
The leg registers its own entry over the production path, a Hub-side click stands
in for the display's pixel hit-test, and the leg pushes the scene the click asked
for — all on its own thread, with nothing polling and no model in the loop.

This is the session-side counterpart of the vox Music Player acceptance scenario:
what a real display would add is the hit-test that turns a click into the
invocation, and the invocation this routes is the one it would send.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, final

import anyio
import pytest
import uvicorn

from punt_lux.domain.hub.replicator_instance import hub_callback_router
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.hub_paths import HubPaths
from punt_lux.luxd import build_app
from punt_lux.operations import RenderRequest
from punt_lux.protocol import TextElement
from punt_lux.session_identity import SessionIdentity
from punt_lux.session_service import SessionCallbackLeg

if TYPE_CHECKING:
    from punt_lux.rest_client import LuxRestClient

pytestmark = pytest.mark.integration


@final
class _EchoService:
    """A session service that renders one text element naming what it serviced."""

    _scene_id: str
    _serviced: list[str]
    __slots__ = ("_scene_id", "_serviced")

    def __new__(cls, scene_id: str) -> Self:
        self = super().__new__(cls)
        self._scene_id = scene_id
        self._serviced = []
        return self

    @property
    def callback_id(self) -> str:
        return "beads"

    @property
    def label(self) -> str:
        return "Beads"

    def service(self, client: LuxRestClient) -> None:
        self._serviced.append(self._scene_id)
        client.render(
            RenderRequest(
                scene_id=self._scene_id,
                elements=[TextElement(id="t", content="serviced").to_dict()],
                title="Serviced",
            )
        )

    @property
    def serviced(self) -> list[str]:
        return self._serviced


@contextmanager
def _running_luxd() -> Generator[int]:
    """Serve the assembled app on an ephemeral loopback port; yield the port."""
    config = uvicorn.Config(build_app(), host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: anyio.run(server.serve), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started:
            raise RuntimeError("luxd did not start within 10s")
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _get(port: int, path: str) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return str(resp.read().decode())


def _until(predicate: Callable[[], bool], *, timeout: float = 10.0) -> None:
    """Spin until the predicate holds — the leg runs on its own thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached within timeout")


def _leaf_id(port: int, label: str) -> str:
    """Return the menu leaf a display would carry back from a click on ``label``."""
    menus = json.loads(_get(port, "/menus"))["menus"]
    for menu in menus:
        for item in menu["items"]:
            if item["label"] == label:
                return str(item["id"])
    raise AssertionError(f"no {label!r} leaf in {menus}")


def test_the_leg_registers_itself_and_services_a_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _running_luxd() as port:
        # Both of the leg's clients resolve luxd through its port file; point them
        # at this test's server, which is the only boundary the test stands in for.
        def _test_port(_paths: HubPaths) -> int:
            return port

        monkeypatch.setattr(HubPaths, "read_port", _test_port)

        identity = SessionIdentity.resolve().client
        service = _EchoService("session-leg-e2e")
        SessionCallbackLeg(identity, service).start()

        # The entry appears under this session's own submenu, with nobody having
        # been asked to register it.
        _until(lambda: identity.name in _get(port, "/menus"))
        leaf = _leaf_id(port, "Beads")

        # Routing the Hub's own leaf id is what a display click does once the pixel
        # hit-test has run; everything after this point is the production path.
        assert hub_callback_router.route(CallbackInvocation.from_menu_id(leaf)) == (
            "routed"
        )
        _until(lambda: service.serviced == ["session-leg-e2e"])

        # And the work reached the Hub: the scene the click asked for is installed,
        # owned by this session's identity.
        _until(lambda: "session-leg-e2e" in _get(port, "/scenes"))
