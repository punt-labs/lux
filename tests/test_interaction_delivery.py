"""Unit tests for InteractionDelivery — the display's outbound interaction leg.

Cover the three delivery routes (scene owner, broadcast, undeliverable) and the
modal-dismiss compensation, driving the collaborator directly with lightweight
stand-ins for the socket server and scene widget state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import ANY, MagicMock

from punt_lux.display.interaction_delivery import InteractionDelivery
from punt_lux.protocol import RemoteEventHandlerInvocation
from punt_lux.scene import WidgetState

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest


def _build(
    *,
    clients: Sequence[object] = (),
    fd_to_client: dict[int, object] | None = None,
    scene_to_owner: dict[str, int] | None = None,
    send_results: dict[object, bool] | None = None,
    widget_state: WidgetState | None = None,
) -> tuple[InteractionDelivery, MagicMock]:
    socket_server = MagicMock()
    socket_server.clients = list(clients)
    socket_server.fd_to_client = fd_to_client or {}
    results = send_results or {}

    def _send(sock: object, _msg: object, _deadline: float) -> bool:
        return results.get(sock, True)

    socket_server.send_to_client.side_effect = _send
    scene_manager = MagicMock()
    scene_manager.scene_to_owner = scene_to_owner or {}
    scene_manager.widget_state_for.return_value = widget_state
    delivery = InteractionDelivery(
        socket_server=socket_server,
        scene_manager=scene_manager,
    )
    return delivery, socket_server


def _modal_closed(
    scene_id: str | None, element_id: str
) -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(
        element_id=element_id,
        action="changed",
        event_kind="modal_closed",
        scene_id=scene_id,
        ts=1.0,
        value=None,
    )


class TestDeliver:
    def test_routes_to_scene_owner(self) -> None:
        owner_sock = object()
        delivery, socket_server = _build(
            fd_to_client={7: owner_sock}, scene_to_owner={"s1": 7}
        )
        event = RemoteEventHandlerInvocation(
            element_id="b", action="click", scene_id="s1", ts=1.0
        )

        assert delivery.deliver([event]) == 1  # one delivered
        socket_server.send_to_client.assert_called_once_with(owner_sock, event, ANY)

    def test_broadcast_sends_to_every_client_without_short_circuit(self) -> None:
        a, b = object(), object()
        delivery, socket_server = _build(clients=[a, b])
        event = RemoteEventHandlerInvocation(element_id="b", action="click", ts=1.0)

        assert delivery.deliver([event]) == 1
        assert socket_server.send_to_client.call_count == 2

    def test_delivery_stops_at_first_unsent_event(self) -> None:
        # A failed send ends the frame: that event and every one after it stay
        # unsent (the prefix count is where delivery stopped), in order.
        dead = object()
        delivery, _ = _build(clients=[dead], send_results={dead: False})
        first = RemoteEventHandlerInvocation(element_id="a", action="click", ts=1.0)
        second = RemoteEventHandlerInvocation(element_id="b", action="click", ts=1.0)

        assert delivery.deliver([first, second]) == 0  # none landed

    def test_delivered_prefix_counts_before_a_stop(self) -> None:
        good, bad = object(), object()
        delivery, _ = _build(
            clients=[good],
            send_results={bad: False},
            fd_to_client={9: bad},
            scene_to_owner={"s9": 9},
        )
        # first broadcasts to `good` (delivered); second targets the dead owner.
        first = RemoteEventHandlerInvocation(element_id="a", action="click", ts=1.0)
        second = RemoteEventHandlerInvocation(
            element_id="b", action="click", scene_id="s9", ts=1.0
        )

        assert delivery.deliver([first, second]) == 1  # only the prefix

    def test_missing_owner_socket_stops_delivery(self) -> None:
        delivery, socket_server = _build(scene_to_owner={"s1": 7})  # fd 7 not mapped
        event = RemoteEventHandlerInvocation(
            element_id="b", action="click", scene_id="s1", ts=1.0
        )

        assert delivery.deliver([event]) == 0
        socket_server.send_to_client.assert_not_called()

    def test_spent_budget_delivers_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A non-positive budget means the deadline is already past: no event is
        # attempted this frame, everything defers.
        monkeypatch.setattr(
            "punt_lux.display.interaction_delivery._FRAME_SEND_BUDGET", -1.0
        )
        sock = object()
        delivery, socket_server = _build(clients=[sock])
        event = RemoteEventHandlerInvocation(element_id="b", action="click", ts=1.0)

        assert delivery.deliver([event]) == 0
        socket_server.send_to_client.assert_not_called()


class TestCompensateEvicted:
    def test_evicted_modal_close_clears_latches(self) -> None:
        ws = WidgetState()
        ws.set(f"m{WidgetState.OPEN_SUFFIX}", 1)
        ws.set(f"m{WidgetState.DISMISS_SUFFIX}", 1)
        delivery, _ = _build(widget_state=ws)

        delivery.compensate_evicted([_modal_closed("s1", "m")])

        assert ws.get(f"m{WidgetState.OPEN_SUFFIX}") is None
        assert ws.get(f"m{WidgetState.DISMISS_SUFFIX}") is None

    def test_evicted_row_selection_clears_pending_slot(self) -> None:
        # An evicted row_selection_changed leaves the optimistic pending selection
        # rendering forever (the Hub, never told, holds the pre-gesture set and a
        # grow-from-empty pick never converges). The eviction must clear it.
        ws = WidgetState()
        ws.set(f"t{WidgetState.ROW_SELECTION_PENDING_SUFFIX}", frozenset({"A"}))
        ws.set(f"t{WidgetState.ROW_SELECTION_HONOURED_SUFFIX}", frozenset())
        delivery, _ = _build(widget_state=ws)
        evicted = RemoteEventHandlerInvocation(
            element_id="t",
            action="changed",
            event_kind="row_selection_changed",
            scene_id="s1",
            ts=1.0,
        )

        delivery.compensate_evicted([evicted])

        assert ws.get(f"t{WidgetState.ROW_SELECTION_PENDING_SUFFIX}") is None
        assert ws.get(f"t{WidgetState.ROW_SELECTION_HONOURED_SUFFIX}") is None

    def test_non_compensated_event_is_ignored(self) -> None:
        ws = WidgetState()
        ws.set(f"m{WidgetState.DISMISS_SUFFIX}", 1)
        delivery, _ = _build(widget_state=ws)
        click = RemoteEventHandlerInvocation(
            element_id="m", action="click", scene_id="s1", ts=1.0
        )

        delivery.compensate_evicted([click])

        assert ws.get(f"m{WidgetState.DISMISS_SUFFIX}") == 1

    def test_scene_less_event_is_ignored(self) -> None:
        delivery, _ = _build(widget_state=None)
        # No scene_id → no widget state to revert; must not raise.
        delivery.compensate_evicted([_modal_closed(None, "m")])
