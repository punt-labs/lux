"""ServiceOperations — register a service, list who serves, relay a request (DES-107).

The relay finds the connection serving ``(service, host)``, sends it a typed
request over its listen leg and waits for the one outcome. Each outcome has one
error code: a reply is the payload; a refusal keeps its code; a deadline is
``timeout``; a lost session is ``provider_lost``; no provider is
``provider_unavailable``; a busy provider is ``rejected``.
"""

from __future__ import annotations

import threading
from typing import Self, final

from punt_lux.hub.call_entry import SessionTicket
from punt_lux.hub.client_calls import ClientCalls, PendingCall
from punt_lux.hub.hub import Hub
from punt_lux.hub.hub_store_factory import HubStoreFactory
from punt_lux.hub.menu_presence import MarkMenusSink
from punt_lux.kernel.client_host import UNOBSERVED
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.kernel.local_host import LocalHost
from punt_lux.operations.services import ServiceOperations
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.model.ids import SceneId
from punt_lux.wire.model.messages.relay_frames import RefusalFrame, ReplyFrame
from punt_lux.wire.model.scope import Scope
from punt_lux.wire.operations.common import OpError
from punt_lux.wire.operations.service_requests import (
    RegisterServiceRequest,
    RelayRequest,
)
from punt_lux.wire.operations.service_results import RelayReply, ServiceList

_PROVIDER = ConnectionId("provider")
_CALLER = ConnectionId("caller")
_HOST = LocalHost.name()


@final
class _Marker:
    def mark_dirty(self, scene_id: SceneId) -> None:
        """Ignore scene marks."""

    def mark_menus(self) -> None:
        """Ignore menu marks."""


@final
class _Leg:
    """A provider's leg: it relays through a real call table and answers on cue."""

    calls: ClientCalls
    answer: object
    ticket: SessionTicket
    __slots__ = ("answer", "calls", "ticket")

    def __new__(cls, deadline_s: float = 5.0) -> Self:
        self = super().__new__(cls)
        self.calls = ClientCalls(boot="t", deadline_s=deadline_s)
        self.ticket = self.calls.open_session()
        self.answer = None
        return self

    def wake(self) -> None:
        """Occupies the slot only."""

    def end_calls(self) -> None:
        self.calls.end_session(self.ticket)

    def relay(
        self, service: str, operation: str, payload: dict[str, object]
    ) -> PendingCall:
        call = self.calls.enter(self.ticket, service, operation, payload)
        answer = self.answer
        request_id = call.frame.request_id
        if isinstance(answer, ReplyFrame):
            reply = answer.model_copy(update={"request_id": request_id})
            threading.Thread(target=self.calls.reply, args=(self.ticket, reply)).start()
        elif isinstance(answer, RefusalFrame):
            refusal = answer.model_copy(update={"request_id": request_id})
            threading.Thread(
                target=self.calls.refuse, args=(self.ticket, refusal)
            ).start()
        return call


def _identity(kind: str = "applet", host: str = _HOST) -> ClientIdentity:
    if kind == "applet":
        return ClientIdentity(
            kind="applet", name="lux · lux · #1 · term", repo="/w/lux", host=host
        )
    return ClientIdentity(kind="cli", name="lux", repo="/w/lux", host=host)


def _ops() -> tuple[ServiceOperations, HubStoreFactory]:
    factory = HubStoreFactory(hub=Hub())
    marker = _Marker()
    factory.lifecycle.present_as(marker, MarkMenusSink(marker))
    return ServiceOperations(factory.lifecycle, factory.clients), factory


def _serving(
    leg: _Leg | None = None, host: str = _HOST
) -> tuple[ServiceOperations, HubStoreFactory, _Leg]:
    ops, factory = _ops()
    leg = leg or _Leg()
    factory.lifecycle.attach(_PROVIDER, _identity(host=host), leg, UNOBSERVED)
    registered = ops.register_service(
        RegisterServiceRequest(service="terminal"),
        scope=Scope.in_process(_PROVIDER),
    )
    assert not isinstance(registered, OpError)
    return ops, factory, leg


def _identify_caller(factory: HubStoreFactory) -> Scope:
    factory.lifecycle.identify(_CALLER, _identity("cli"), UNOBSERVED)
    return Scope.in_process(_CALLER)


def test_a_connection_with_a_leg_registers_and_is_listed() -> None:
    ops, _, _ = _serving()

    listing = ops.list_services(scope=Scope.in_process(_PROVIDER))

    assert isinstance(listing, ServiceList)
    assert [(s.service, s.host) for s in listing.services] == [("terminal", _HOST)]


def test_registering_with_no_leg_is_push_required() -> None:
    ops, factory = _ops()
    factory.lifecycle.identify(_PROVIDER, _identity(), UNOBSERVED)

    result = ops.register_service(
        RegisterServiceRequest(service="terminal"), scope=Scope.in_process(_PROVIDER)
    )

    assert isinstance(result, OpError)
    assert result.code == "push_required"


def test_claiming_a_held_key_is_rejected() -> None:
    ops, factory, _ = _serving()
    other = ConnectionId("other")
    factory.lifecycle.attach(other, _identity(), _Leg(), UNOBSERVED)

    result = ops.register_service(
        RegisterServiceRequest(service="terminal"), scope=Scope.in_process(other)
    )

    assert isinstance(result, OpError)
    assert result.code == "rejected"


def test_a_reply_is_the_relayed_payload() -> None:
    ops, factory, leg = _serving()
    leg.answer = ReplyFrame(request_id="x", payload={"id": "t3"})
    scope = _identify_caller(factory)

    result = ops.relay(
        RelayRequest(service="terminal", operation="new", payload={"label": "b"}),
        scope=scope,
    )

    assert result == RelayReply(payload={"id": "t3"})


def test_an_omitted_host_means_the_hubs_own_host() -> None:
    ops, factory, leg = _serving(host=_HOST)
    leg.answer = ReplyFrame(request_id="x", payload={})
    scope = _identify_caller(factory)

    result = ops.relay(RelayRequest(service="terminal", operation="ls"), scope=scope)

    assert isinstance(result, RelayReply)


def test_a_refusal_keeps_its_code_and_reason() -> None:
    ops, factory, leg = _serving()
    leg.answer = RefusalFrame(request_id="x", code="not_found", reason="no session")
    scope = _identify_caller(factory)

    result = ops.relay(RelayRequest(service="terminal", operation="kill"), scope=scope)

    assert result == OpError(code="not_found", reason="no session")


def test_a_provider_that_never_answers_is_a_timeout_naming_it() -> None:
    ops, factory, _ = _serving(_Leg(deadline_s=0.05))
    scope = _identify_caller(factory)

    result = ops.relay(RelayRequest(service="terminal", operation="ls"), scope=scope)

    assert isinstance(result, OpError)
    assert result.code == "timeout"
    assert "terminal" in result.reason
    assert _HOST in result.reason


def test_a_provider_whose_session_ends_first_is_provider_lost() -> None:
    ops, factory, leg = _serving()
    scope = _identify_caller(factory)
    result: list[object] = []
    worker = threading.Thread(
        target=lambda: result.append(
            ops.relay(RelayRequest(service="terminal", operation="ls"), scope=scope)
        )
    )
    worker.start()
    while not leg.calls._pending:
        pass
    leg.end_calls()
    worker.join(timeout=5)

    outcome = result[0]
    assert isinstance(outcome, OpError)
    assert outcome.code == "provider_lost"


def test_no_provider_is_unavailable_and_names_the_hosts_that_answer() -> None:
    ops, factory, _ = _serving(host="pembroke")
    scope = _identify_caller(factory)

    result = ops.relay(
        RelayRequest(service="terminal", operation="ls", host="nowhere"), scope=scope
    )

    assert isinstance(result, OpError)
    assert result.code == "provider_unavailable"
    assert "pembroke" in result.reason


def test_an_unidentified_caller_is_challenged() -> None:
    ops, _, _ = _serving()

    result = ops.relay(
        RelayRequest(service="terminal", operation="ls"),
        scope=Scope.in_process(ConnectionId("stranger")),
    )

    assert isinstance(result, OpError)
    assert result.code == "identification_required"


def test_a_busy_provider_is_rejected_and_nothing_is_sent() -> None:
    ops, factory, leg = _serving()
    scope = _identify_caller(factory)
    for _ in range(ClientCalls.PER_SESSION_LIMIT):
        leg.calls.enter(leg.ticket, "terminal", "ls", {})

    result = ops.relay(RelayRequest(service="terminal", operation="ls"), scope=scope)

    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert "busy" in result.reason
