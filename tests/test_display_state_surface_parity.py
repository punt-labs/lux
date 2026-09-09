"""``display_state`` -- one shared Operations facade, four surfaces, one shape.

Drives the MCP tool, the REST route, the CLI command, and a direct library
call against the SAME ``Operations`` instance and ``StubPort`` payload, then
compares the parsed JSON payload field-for-field (python.md's Surface Parity
Testing pattern) -- the class of test that catches a surface silently
dropping or renaming a field that another surface still reports.

Every surface resolves the SAME caller identity (``DEFAULT_IDENTITY_MODEL`` /
``DEFAULT_CONNECTION``, shared with the REST route tests), because
``display_state`` is now scoped to the caller's own connection -- comparing
across surfaces only makes sense when they are asking on behalf of the same
connection.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from punt_lux.__main__ import app as cli_app
from punt_lux.commands import Ctx
from punt_lux.commands.display_state_get import DisplayStateOps, display_state_get
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.operations import Scope
from punt_lux.operations.display_reply import DisplayReplied
from punt_lux.rest import RestSurface
from tests.rest._fakes import (
    DEFAULT_CONNECTION,
    DEFAULT_IDENTITY,
    DEFAULT_IDENTITY_MODEL,
    StubPort,
    make_facade,
)

if TYPE_CHECKING:
    import pytest

    from punt_lux.operations import Operations

_S1 = ConnectionScopedId.compose(DEFAULT_CONNECTION, "s1")
_SCOPE = Scope(DEFAULT_CONNECTION)

_PAYLOAD = {
    "scenes": {_S1: {"checkbox1": True, "count": 3.0}},
    "frames": [
        {
            "frame_id": "f1",
            "visibility": "on_screen",
            "active_tab": _S1,
            "cascade_index": 0,
        }
    ],
}

_EXPECTED = {
    "kind": "ok",
    "scenes": {"s1": {"values": {"checkbox1": True, "count": 3.0}}},
    "frames": [
        {
            "frame_id": "f1",
            "visibility": "on_screen",
            "active_tab": "s1",
            "cascade_index": 0,
        }
    ],
}


def _shared_facade() -> Operations:
    """One fresh Operations facade, backed by one fixed display-state payload."""
    return make_facade(display_port=StubPort(DisplayReplied(_PAYLOAD)))


def test_mcp_tool_matches_the_expected_shape() -> None:
    facade = _shared_facade()
    ctx: Ctx[DisplayStateOps] = Ctx(ops=facade, identity=DEFAULT_IDENTITY_MODEL)

    result = asyncio.run(display_state_get.execute(ctx, scope=_SCOPE))

    assert result.model_dump(mode="json") == _EXPECTED


def test_rest_route_matches_the_expected_shape() -> None:
    facade = _shared_facade()
    app = FastAPI()
    RestSurface(facade).mount(app)
    client = TestClient(app)

    resp = client.get("/display/state", headers=DEFAULT_IDENTITY)

    assert resp.status_code == 200
    assert resp.json() == _EXPECTED


def test_cli_matches_the_expected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    facade = _shared_facade()

    def _stub_connect(**_kw: object) -> Operations:
        return facade

    def _stub_resolve(override: str | None = None) -> ClientIdentity:
        del override
        return DEFAULT_IDENTITY_MODEL

    monkeypatch.setattr("punt_lux.cli.display.connect_client", _stub_connect)
    monkeypatch.setattr("punt_lux.cli._shared.CliIdentity.resolve", _stub_resolve)
    runner = CliRunner()

    result = runner.invoke(cli_app, ["display", "state", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == _EXPECTED


def test_library_facade_call_matches_the_expected_shape() -> None:
    facade = _shared_facade()

    result = facade.get_display_state(scope=_SCOPE)

    assert result.model_dump(mode="json") == _EXPECTED
