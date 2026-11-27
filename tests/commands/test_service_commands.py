"""Direct tests for the ``service register`` and ``service ls`` commands (PL-TT-5)."""

from __future__ import annotations

import asyncio
from typing import Self, final

from punt_lux.commands import Ctx
from punt_lux.commands.service_ls import service_ls
from punt_lux.commands.service_register import service_register
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.operations import Ok, OpError, Scope
from punt_lux.wire.operations.service_requests import RegisterServiceRequest
from punt_lux.wire.operations.service_results import ServiceEntry, ServiceList
from punt_lux.wire.ops import ServiceOps
from tests.commands._scene_stub import identity

_SCOPE = Scope.in_process(ConnectionId("test-conn"))


@final
class _StubServiceOps:
    """``ServiceOps`` stub returning preset outcomes; records routing args."""

    register_result: Ok | OpError
    listing: ServiceList
    last_call: dict[str, object]
    __slots__ = ("last_call", "listing", "register_result")

    def __new__(
        cls,
        register_result: Ok | OpError | None = None,
        listing: ServiceList | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self.register_result = register_result if register_result else Ok()
        self.listing = listing if listing else ServiceList(services=[])
        self.last_call = {}
        return self

    def register_service(
        self, request: RegisterServiceRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        self.last_call = {
            "method": "register_service",
            "request": request,
            "scope": scope,
        }
        return self.register_result

    def list_services(self, *, scope: Scope) -> ServiceList:
        self.last_call = {"method": "list_services", "scope": scope}
        return self.listing


def _ctx(ops: _StubServiceOps) -> Ctx[ServiceOps]:
    return Ctx(ops=ops, identity=identity())


def test_register_renders_the_service_name() -> None:
    ops = _StubServiceOps()

    result = asyncio.run(
        service_register(
            _ctx(ops), RegisterServiceRequest(service="terminal"), scope=_SCOPE
        )
    )

    assert result.text == "registered:terminal"
    assert result.error is False
    assert result.json_data == {"service": "terminal"}


def test_register_routes_the_request_and_scope_to_ops() -> None:
    ops = _StubServiceOps()
    request = RegisterServiceRequest(service="terminal")

    asyncio.run(service_register(_ctx(ops), request, scope=_SCOPE))

    assert ops.last_call == {
        "method": "register_service",
        "request": request,
        "scope": _SCOPE,
    }


def test_register_renders_a_refusal_as_an_error_line() -> None:
    ops = _StubServiceOps(
        register_result=OpError(code="push_required", reason="no listen leg")
    )

    result = asyncio.run(
        service_register(
            _ctx(ops), RegisterServiceRequest(service="terminal"), scope=_SCOPE
        )
    )

    assert result.text == "error: no listen leg"
    assert result.error is True


def test_register_passes_a_parse_error_through_as_an_error_line() -> None:
    ops = _StubServiceOps()
    parse_error = OpError(code="invalid_request", reason="service: too short")

    result = asyncio.run(service_register(_ctx(ops), parse_error, scope=_SCOPE))

    assert result.text == "error: service: too short"
    assert result.error is True
    assert ops.last_call == {}


def test_ls_renders_one_line_per_registration() -> None:
    ops = _StubServiceOps(
        listing=ServiceList(
            services=[
                ServiceEntry(service="album", host="okinos"),
                ServiceEntry(service="terminal", host="okinos"),
            ]
        )
    )

    result = asyncio.run(service_ls(_ctx(ops), scope=_SCOPE))

    assert result.text == "album okinos\nterminal okinos"
    assert result.error is False
    assert result.json_data == {
        "kind": "ok",
        "services": [
            {"service": "album", "host": "okinos"},
            {"service": "terminal", "host": "okinos"},
        ],
    }


def test_ls_of_no_registrations_says_so() -> None:
    result = asyncio.run(service_ls(_ctx(_StubServiceOps()), scope=_SCOPE))

    assert result.text == "no services registered"
    assert result.error is False
