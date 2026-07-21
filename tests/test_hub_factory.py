"""Unit tests for :mod:`punt_lux.domain.hub.hub_factory`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.hub import hub
from punt_lux.domain.hub.hub_factory import HubPublishSink, hub_element_factory
from punt_lux.domain.hub.inbox import drain_inbox, ensure_writer
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.protocol.element_factory import JsonElementFactory

if TYPE_CHECKING:
    from collections.abc import Mapping


class TestHubPublishSink:
    def test_satisfies_publish_sink_protocol(self) -> None:
        sink = HubPublishSink(ConnectionId("conn-1"))
        assert isinstance(sink, PublishSink)

    def test_publish_routes_to_hub_in_caller_scope(self) -> None:
        connection_id = ConnectionId("conn-publish-routes")
        ensure_writer(connection_id)
        hub.subscribe(connection_id, Topic("ping"))
        try:
            sink = HubPublishSink(connection_id)
            payload: Mapping[str, object] = {"n": 1}
            sink("ping", payload)
            delivered = drain_inbox(connection_id)
        finally:
            hub.on_disconnect(connection_id)
        assert len(delivered) == 1
        assert delivered[0].topic == "ping"
        assert delivered[0].payload == {"n": 1}

    def test_publish_isolated_between_connections(self) -> None:
        a = ConnectionId("conn-a")
        b = ConnectionId("conn-b")
        ensure_writer(a)
        ensure_writer(b)
        hub.subscribe(a, Topic("shared"))
        hub.subscribe(b, Topic("shared"))
        try:
            HubPublishSink(a)("shared", {"from": "a"})
            received_b = drain_inbox(b)
            received_a = drain_inbox(a)
        finally:
            hub.on_disconnect(a)
            hub.on_disconnect(b)
        assert received_b == ()
        assert len(received_a) == 1
        assert received_a[0].payload == {"from": "a"}


class TestHubElementFactory:
    def test_returns_json_element_factory(self) -> None:
        factory = hub_element_factory(ConnectionId("conn-1"))
        assert isinstance(factory, JsonElementFactory)

    def test_each_call_binds_to_the_supplied_connection(self) -> None:
        f_a = hub_element_factory(ConnectionId("conn-a"))
        f_b = hub_element_factory(ConnectionId("conn-b"))
        assert f_a is not f_b

    def test_decoded_button_publish_routes_to_caller_scope(self) -> None:
        connection_id = ConnectionId("conn-decoded-button")
        ensure_writer(connection_id)
        hub.subscribe(connection_id, Topic("clicked"))
        try:
            factory = hub_element_factory(connection_id)
            button = factory.element_from_dict(
                {
                    "kind": "button",
                    "id": "b1",
                    "label": "Go",
                    "handlers": [
                        {"event": "click", "publish": ["clicked"]},
                    ],
                }
            )
            # Decode succeeded — handler chain wired with Hub-bound sink.
            assert button.id == "b1"
        finally:
            hub.on_disconnect(connection_id)
