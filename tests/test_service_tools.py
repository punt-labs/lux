"""service_register and service_ls MCP tools -- zero-logic adapters over the facade.

The tools run against an isolated store so the adapter wiring is exercised end
to end: parse, scope from the session key, facade call, status line or raise.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest import mock

import pytest
from fastmcp.exceptions import ToolError

from punt_lux.hub.hub_store_factory import HubStoreFactory
from punt_lux.kernel.client_host import UNOBSERVED
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.tools import tools as _core
from punt_lux.tools.server import _session_key
from punt_lux.tools.service_tools import service_ls, service_register
from punt_lux.wire.model.client_identity import ClientIdentity
from tests.rest._fakes import ForbiddenPort, SilentListener, make_facade

_SESSION = "test-service-tools"
_IDENTITY = ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


@pytest.fixture
def factory() -> Generator[HubStoreFactory]:
    """Rebind the tools' facade to an isolated store for one test."""
    built = HubStoreFactory()
    facade = make_facade(display_port=ForbiddenPort(), factory=built)
    token = _session_key.set(_SESSION)
    with mock.patch.object(_core, "OPERATIONS", facade):
        yield built
    _session_key.reset(token)


def _attach_leg(factory: HubStoreFactory) -> None:
    factory.lifecycle.attach(
        ConnectionId(_SESSION), _IDENTITY, SilentListener(), UNOBSERVED
    )


def test_ls_of_no_registrations_says_so(factory: HubStoreFactory) -> None:
    assert service_ls() == "no services registered"


def test_register_with_a_leg_is_listed(factory: HubStoreFactory) -> None:
    _attach_leg(factory)

    assert service_register("terminal") == "registered:terminal"
    assert service_ls().startswith("terminal ")


def test_register_with_no_leg_is_refused(factory: HubStoreFactory) -> None:
    with pytest.raises(ToolError, match="listen"):
        service_register("terminal")


def test_register_of_a_malformed_name_is_refused(factory: HubStoreFactory) -> None:
    _attach_leg(factory)

    with pytest.raises(ToolError):
        service_register("Not A Name")
