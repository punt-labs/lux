"""``display_link`` -- one shared Operations facade, four surfaces, one shape.

Drives the MCP tool, the REST route, the CLI command, and a direct library
call against the SAME ``Operations`` instance, for both the connected and the
disconnected/held cases, then compares the parsed JSON payload field-for-field
(python.md's Surface Parity Testing pattern) -- the discriminated ``kind`` and
its shape-specific fields (``linkage``, ``retry_delay_seconds``) must survive
identically across every surface, with no silent drop or rename.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from punt_lux.__main__ import app as cli_app
from punt_lux.operations.display_reply import DisplayReplied
from punt_lux.rest import RestSurface
from punt_lux.tools.read_tools import get_display_link
from tests.rest._fakes import ForbiddenPort, StubPort, make_facade

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Operations

_CONNECTED = {"kind": "connected", "linkage": "connected_idle"}
_DISCONNECTED = {
    "kind": "disconnected",
    "linkage": "disconnected",
    "retry_delay_seconds": 0.0,
}


def _connected_facade() -> Operations:
    """A facade backed by a display that has answered -- connected, idle."""
    return make_facade(display_port=StubPort(DisplayReplied({})))


def _disconnected_facade() -> Operations:
    """A facade with no display attached -- ``get_link`` never proxies to it."""
    return make_facade(display_port=ForbiddenPort())


def _stub_connect(
    facade: Operations,
) -> Callable[..., SyncOps]:
    """Return a ``connect_client``-shaped stub that hands back *facade* directly."""

    def _connect(
        *, identity: ClientIdentity | None = None, timeout: float = 2.0
    ) -> SyncOps:
        del identity, timeout
        return cast("SyncOps", facade)

    return _connect


class TestConnected:
    """Every surface reports the same connected/idle shape."""

    def test_mcp_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("punt_lux.tools.tools.OPERATIONS", _connected_facade())

        result = get_display_link()

        assert result.model_dump(mode="json") == _CONNECTED

    def test_rest_route(self) -> None:
        app = FastAPI()
        RestSurface(_connected_facade()).mount(app)

        resp = TestClient(app).get("/display/link")

        assert resp.status_code == 200
        assert resp.json() == _CONNECTED

    def test_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade = _connected_facade()
        monkeypatch.setattr(
            "punt_lux.cli.display_link.connect_client", _stub_connect(facade)
        )
        runner = CliRunner()

        result = runner.invoke(cli_app, ["display", "link", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout) == _CONNECTED

    def test_library_facade_call(self) -> None:
        facade = _connected_facade()

        result = facade.get_link()

        assert result.model_dump(mode="json") == _CONNECTED


class TestDisconnected:
    """Every surface reports the same disconnected shape, with its retry delay."""

    def test_mcp_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("punt_lux.tools.tools.OPERATIONS", _disconnected_facade())

        result = get_display_link()

        assert result.model_dump(mode="json") == _DISCONNECTED

    def test_rest_route(self) -> None:
        app = FastAPI()
        RestSurface(_disconnected_facade()).mount(app)

        resp = TestClient(app).get("/display/link")

        assert resp.status_code == 200
        assert resp.json() == _DISCONNECTED

    def test_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade = _disconnected_facade()
        monkeypatch.setattr(
            "punt_lux.cli.display_link.connect_client", _stub_connect(facade)
        )
        runner = CliRunner()

        result = runner.invoke(cli_app, ["display", "link", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout) == _DISCONNECTED

    def test_library_facade_call(self) -> None:
        facade = _disconnected_facade()

        result = facade.get_link()

        assert result.model_dump(mode="json") == _DISCONNECTED
