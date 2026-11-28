"""A listener built through the facade answers relayed requests with its handler."""

from __future__ import annotations

from collections.abc import Mapping
from unittest import mock

from punt_lux.client._rest_transport import _RestTransport
from punt_lux.client.facade import LuxClient
from punt_lux.client.hub_client import LuxHubClient
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.operations import Scope

_IDENTITY = ClientIdentity(kind="cli", name="listener-test", repo="/w/lux")


def _answer(_s: str, _o: str, _p: Mapping[str, object]) -> Mapping[str, object]:
    return {}


def _noop(*_args: object) -> None:
    return None


def test_the_transport_listener_hands_on_request_to_the_hub_client() -> None:
    transport = _RestTransport(mock.Mock(), _IDENTITY)

    with mock.patch.object(LuxHubClient, "connect") as connect:
        transport.listener(on_callback=_noop, on_event=_noop, on_request=_answer)

    assert connect.call_args.kwargs["on_request"] is _answer


def test_the_facade_listener_hands_on_request_to_the_transport() -> None:
    transport = mock.Mock()
    client = LuxClient(transport, _IDENTITY)

    client.listener(on_callback=_noop, on_event=_noop, on_request=_answer)

    assert transport.listener.call_args.kwargs["on_request"] is _answer
    assert isinstance(client.scope, Scope)
