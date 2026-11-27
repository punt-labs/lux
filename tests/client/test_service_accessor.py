"""ServiceAccessor — the ``client.service.*`` verbs over a REST transport (DES-107)."""

from __future__ import annotations

import asyncio

from punt_lux.client._rest_transport import _RestTransport
from punt_lux.client.rest_transport import HttpResponse
from punt_lux.client.service import ServiceAccessor
from punt_lux.wire.operations import Ok, OpError
from tests.client.test_rest_transport import CannedTransport, SurfaceTransport
from tests.rest._fakes import DEFAULT_IDENTITY_MODEL, make_client


def _accessor(transport: object) -> ServiceAccessor:
    rest = _RestTransport(transport, DEFAULT_IDENTITY_MODEL)  # type: ignore[arg-type]  # HttpTransport protocol; fakes satisfy it structurally
    return ServiceAccessor.over(rest)


def test_register_posts_the_name_to_the_services_route() -> None:
    transport = CannedTransport(HttpResponse(status=200, body=b'{"kind":"ok"}'))

    result = asyncio.run(_accessor(transport).register("terminal"))

    assert result == Ok()
    assert transport.call is not None
    assert (transport.call.method, transport.call.path) == ("POST", "/services")
    assert transport.call.body is not None
    assert b'"terminal"' in transport.call.body


def test_register_with_a_malformed_name_is_refused_without_a_round_trip() -> None:
    transport = CannedTransport(HttpResponse(status=200, body=b'{"kind":"ok"}'))

    result = asyncio.run(_accessor(transport).register("Not A Name"))

    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert transport.call is None


def test_ls_reads_the_services_route() -> None:
    body = b'{"kind":"ok","services":[{"service":"terminal","host":"okinos"}]}'
    transport = CannedTransport(HttpResponse(status=200, body=body))

    result = asyncio.run(_accessor(transport).ls())

    assert not isinstance(result, OpError)
    assert [(s.service, s.host) for s in result.services] == [("terminal", "okinos")]
    assert transport.call is not None
    assert (transport.call.method, transport.call.path) == ("GET", "/services")


def test_a_registration_refusal_keeps_the_hubs_exact_code() -> None:
    body = b'{"detail":"no listen leg","code":"push_required"}'
    transport = CannedTransport(HttpResponse(status=403, body=body))

    result = asyncio.run(_accessor(transport).register("terminal"))

    assert result == OpError(code="push_required", reason="no listen leg")


def test_the_verbs_agree_with_the_real_routes() -> None:
    accessor = _accessor(SurfaceTransport(make_client(listening=True)))

    assert asyncio.run(accessor.register("terminal")) == Ok()
    listed = asyncio.run(accessor.ls())

    assert not isinstance(listed, OpError)
    assert [s.service for s in listed.services] == ["terminal"]
