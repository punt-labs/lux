"""Operations exposes the service operations beside every other capability.

The facade composes concern classes and delegates; it adds no behavior of its own,
so these tests pin only that each service method reaches the services concern with
the caller's scope.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.operations.concerns import OperationsConcerns
from punt_lux.operations.facade import Operations
from punt_lux.wire.model.scope import Scope
from punt_lux.wire.operations.menu_results import Ok
from punt_lux.wire.operations.service_requests import (
    RegisterServiceRequest,
    RelayRequest,
)
from punt_lux.wire.operations.service_results import RelayReply, ServiceList


@final
class _Services:
    """A services concern that records what the facade passed it."""

    calls: list[tuple[str, object, Scope]]
    __slots__ = ("calls",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.calls = []
        return self

    def register_service(self, request: object, *, scope: Scope) -> Ok:
        self.calls.append(("register", request, scope))
        return Ok()

    def list_services(self, *, scope: Scope) -> ServiceList:
        self.calls.append(("list", None, scope))
        return ServiceList(services=[])

    def relay(self, request: object, *, scope: Scope) -> RelayReply:
        self.calls.append(("relay", request, scope))
        return RelayReply(payload={"ok": 1})


def _facade() -> tuple[Operations, _Services]:
    services = _Services()
    sentinel = object()
    concerns = OperationsConcerns(
        scenes=sentinel,  # type: ignore[arg-type]
        pubsub=sentinel,  # type: ignore[arg-type]
        config=sentinel,  # type: ignore[arg-type]
        display=sentinel,  # type: ignore[arg-type]
        queries=sentinel,  # type: ignore[arg-type]
        menus=sentinel,  # type: ignore[arg-type]
        identity=sentinel,  # type: ignore[arg-type]
        callbacks=sentinel,  # type: ignore[arg-type]
        frame_remover=sentinel,  # type: ignore[arg-type]
        link=sentinel,  # type: ignore[arg-type]
        services=services,  # type: ignore[arg-type]
    )
    return Operations(concerns), services


_SCOPE = Scope.in_process(ConnectionId("c1"))


def test_register_service_reaches_the_services_concern() -> None:
    facade, services = _facade()
    request = RegisterServiceRequest(service="terminal")

    assert facade.register_service(request, scope=_SCOPE) == Ok()
    assert services.calls == [("register", request, _SCOPE)]


def test_list_services_reaches_the_services_concern() -> None:
    facade, services = _facade()

    assert facade.list_services(scope=_SCOPE) == ServiceList(services=[])
    assert services.calls == [("list", None, _SCOPE)]


def test_relay_reaches_the_services_concern() -> None:
    facade, services = _facade()
    request = RelayRequest(service="terminal", operation="ls")

    assert facade.relay(request, scope=_SCOPE) == RelayReply(payload={"ok": 1})
    assert services.calls == [("relay", request, _SCOPE)]
