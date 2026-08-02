"""The REST surface assembly, the route-parity guard, and luxd boot.

The parity guard is the completeness net: every public facade operation is either
reachable over REST or in a small, documented MCP-only set. A new operation added
to the facade with no route and no exemption fails this test, so REST cannot
silently fall behind the engine.
"""

from __future__ import annotations

import inspect

from fastapi.routing import APIRoute

from punt_lux.operations.facade import Operations
from punt_lux.rest import HubHealth, RestSurface

from ._fakes import ForbiddenPort, make_facade

# Operations that live in the facade but are not routed over REST, each with the
# design's reason. publish/subscribe/unsubscribe/receive are session-scoped and
# blocked on the REST session decision — a connection-less REST publish in one
# fixed scope can never deliver, so it is not exposed; drop_session is session
# lifecycle. identify is the MCP session's first-call; REST per-request identity
# resolution is a later step, so identify carries no REST route yet.
# render_table/render_dashboard ARE routed: a composed table must be CONSTRUCTED
# server-side (its handlers + model are not wire-expressible), so a REST caller
# pushing composed JSON through the generic render gets dead chrome.
# show_client_details is neither: it is the Hub answering its own menu command.
# It is keyed by a ConnectionId — a wire key, not part of REST's addressing — and
# it writes a scene owned by a connection other than the caller's, which no
# routed operation may do, so it has no route rather than a scoped one.
_MCP_ONLY = {
    "show_client_details",
    "publish",
    "subscribe",
    "unsubscribe",
    "receive",
    "drop_session",
    "identify",
}


def _facade_operations() -> set[str]:
    members = inspect.getmembers(Operations, predicate=inspect.isfunction)
    return {
        name for name, _ in members if not name.startswith("_") and name != "for_store"
    }


def _routed_operations() -> set[str]:
    surface = RestSurface(make_facade(display_port=ForbiddenPort()))
    return {
        route.name
        for router in surface.routers
        for route in router.routes
        if isinstance(route, APIRoute)
    }


def test_every_facade_operation_is_routed_or_exempt() -> None:
    routed = _routed_operations()
    unrouted = _facade_operations() - routed - _MCP_ONLY
    assert unrouted == set(), f"facade operations with no REST route: {unrouted}"


def test_no_route_names_an_operation_the_facade_lacks() -> None:
    assert _routed_operations() <= _facade_operations()


def test_routed_and_exempt_sets_are_disjoint() -> None:
    # An operation cannot be both routed and MCP-only-exempt: if it were, losing
    # its route would leave every guard green (the exemption would mask the gap).
    assert _routed_operations().isdisjoint(_MCP_ONLY)


def test_exempt_set_names_only_real_operations() -> None:
    # A stale exemption (an op that no longer exists) would silently mask a
    # missing route; keep the set honest.
    assert _facade_operations() >= _MCP_ONLY


def test_surface_exposes_one_router_per_concern() -> None:
    surface = RestSurface(make_facade(display_port=ForbiddenPort()))
    assert len(surface.routers) == 4


def test_no_publish_route_is_mounted() -> None:
    # Pub-sub is session-scoped and blocked on the REST session decision; a 200
    # that can never deliver is worse than no route, so publish is not routed.
    assert "publish" not in _routed_operations()


def test_hub_health_serializes_status_and_sessions() -> None:
    health = HubHealth(sessions=3)
    assert health.model_dump() == {"status": "ok", "sessions": 3}
