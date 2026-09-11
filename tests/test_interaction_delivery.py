"""Unit tests for InteractionDelivery — the display's outbound interaction leg.

Cover the two delivery routes (scene owner, declared Hub) and the undeliverable
case -- there is no broadcast fallback -- plus the eviction compensation for
every interaction kind that latches display-side state, driving the
collaborator directly with lightweight stand-ins for the socket server and
scene widget state.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display.evictions import Evictions
from punt_lux.display.interaction_delivery import InteractionDelivery
from punt_lux.display.pending_interactions import PendingInteractions
from punt_lux.display.replica import WidgetState
from punt_lux.protocol import RemoteEventHandlerInvocation


def _build(
    *,
    fd_to_client: dict[int, object] | None = None,
    scene_to_owner: dict[str, int] | None = None,
    hub_fds: dict[str, int] | None = None,
    send_results: dict[object, bool] | None = None,
    widget_state: WidgetState | None = None,
) -> tuple[InteractionDelivery, MagicMock]:
    socket_listener = MagicMock()
    socket_listener.fd_to_client = fd_to_client or {}
    socket_listener.fd_for_hub_token.side_effect = (hub_fds or {}).get
    results = send_results or {}

    def _send(sock: object, _msg: object) -> bool:
        return results.get(sock, True)

    socket_listener.send_to_client.side_effect = _send
    scenes = MagicMock()
    scenes.scene_to_owner = scene_to_owner or {}
    scenes.widget_state_for.return_value = widget_state
    delivery = InteractionDelivery(
        socket_listener=socket_listener,
        scenes=scenes,
    )
    return delivery, socket_listener


def _evicted(
    event_kind: str, element_id: str, scene_id: str | None = "s1"
) -> RemoteEventHandlerInvocation:
    """Return an invocation of ``event_kind`` as the pending buffer held it."""
    return RemoteEventHandlerInvocation(
        element_id=element_id,
        action="changed",
        event_kind=event_kind,
        scene_id=scene_id,
        ts=1.0,
        value=None,
    )


def _lost(*events: RemoteEventHandlerInvocation) -> Evictions:
    """Return ``events`` as the buffer reports them with nothing left holding."""
    return Evictions.of(events, ())


def _aged_out_while_newer_held(
    event_kind: str, element_id: str
) -> tuple[Evictions, PendingInteractions]:
    """Age one gesture out of a real buffer while a second one is still held.

    The user interacts twice in quick succession -- two toggles of a header, two
    tab switches, two commits of an edit -- and the first ages out before the
    Hub answers. The buffer is the real one, so the split under test is the one
    the display's flush actually produces.
    """
    buf = PendingInteractions(max_age=3.0, max_count=128)
    buf.admit([_evicted(event_kind, element_id)], now=100.0)
    buf.admit([_evicted(event_kind, element_id)], now=103.5)
    return buf.expire(now=104.0), buf


class TestDeliver:
    def test_routes_to_scene_owner(self) -> None:
        owner_sock = object()
        delivery, socket_listener = _build(
            fd_to_client={7: owner_sock}, scene_to_owner={"s1": 7}
        )
        event = RemoteEventHandlerInvocation(
            element_id="b", action="click", scene_id="s1", ts=1.0
        )

        assert delivery.deliver([event]) == ((event,), ())  # delivered, none dropped
        socket_listener.send_to_client.assert_called_once_with(owner_sock, event)

    def test_routes_a_scene_less_event_to_its_declared_hub(self) -> None:
        # A menu-sourced event carries no scene -- it carries the HubId its
        # menu was replicated from instead, so delivery names that one Hub's
        # connection rather than guessing.
        hub_sock = object()
        delivery, socket_listener = _build(
            fd_to_client={9: hub_sock}, hub_fds={"hub-a": 9}
        )
        event = RemoteEventHandlerInvocation(
            element_id="m", action="menu", ts=1.0, hub_token="hub-a"
        )

        assert delivery.deliver([event]) == ((event,), ())
        socket_listener.send_to_client.assert_called_once_with(hub_sock, event)

    def test_a_menu_click_never_reaches_a_second_live_hub(self) -> None:
        # Two Hubs connected; a click declaring hub-a's token must resolve to
        # hub-a's own connection only -- the misrouting a broadcast risked.
        a_sock, b_sock = object(), object()
        delivery, socket_listener = _build(
            fd_to_client={9: a_sock, 10: b_sock}, hub_fds={"hub-a": 9, "hub-b": 10}
        )
        event = RemoteEventHandlerInvocation(
            element_id="m", action="menu", ts=1.0, hub_token="hub-a"
        )

        delivery.deliver([event])

        sent_to = [c.args[0] for c in socket_listener.send_to_client.call_args_list]
        assert sent_to == [a_sock]  # exactly hub-a's socket, never hub-b's

    def test_a_scene_less_hub_less_event_is_dropped_not_held(self) -> None:
        # No scene, no declared Hub: unroutable now and forever, so dropped --
        # removed and compensated at once, never left stuck in the buffer.
        delivery, socket_listener = _build()
        event = RemoteEventHandlerInvocation(element_id="b", action="click", ts=1.0)

        assert delivery.deliver([event]) == ((event,), (event,))  # removed, dropped
        socket_listener.send_to_client.assert_not_called()

    def test_an_unresolvable_hub_token_is_deferred_not_dropped(self) -> None:
        # The declared Hub is absent this instant -- perhaps mid-reconnect -- so
        # the click is deferred: neither sent nor dropped, and kept in the buffer
        # (removed is empty) so a reconnect within the window can still deliver it.
        delivery, socket_listener = _build()
        event = RemoteEventHandlerInvocation(
            element_id="m", action="menu", ts=1.0, hub_token="absent-hub"
        )

        assert delivery.deliver([event]) == ((), ())  # kept, not dropped
        socket_listener.send_to_client.assert_not_called()

    def test_a_deferred_event_does_not_stall_a_later_deliverable_one(self) -> None:
        """A menu click whose Hub is absent is held (deferred), yet must not
        stall a deliverable click behind it: the deliverable one still goes."""
        good_sock = object()
        delivery, socket_listener = _build(
            fd_to_client={9: good_sock}, hub_fds={"hub-a": 9}
        )
        deferred = RemoteEventHandlerInvocation(
            element_id="m1", action="menu", ts=1.0, hub_token="absent-hub"
        )
        deliverable = RemoteEventHandlerInvocation(
            element_id="m2", action="menu", ts=1.0, hub_token="hub-a"
        )

        removed, dropped = delivery.deliver([deferred, deliverable])

        assert removed == (deliverable,)  # only the deliverable one leaves the buffer
        assert dropped == ()  # the deferred one is neither sent nor dropped -- held
        socket_listener.send_to_client.assert_called_once_with(good_sock, deliverable)

    def test_delivery_stops_at_first_unsent_event(self) -> None:
        # A failed send ends the frame: that event and every one after it stay
        # unsent (removed is empty -- delivery stopped at the block), in order.
        dead = object()
        delivery, _ = _build(
            fd_to_client={9: dead}, hub_fds={"hub-a": 9}, send_results={dead: False}
        )
        first = RemoteEventHandlerInvocation(
            element_id="a", action="click", ts=1.0, hub_token="hub-a"
        )
        second = RemoteEventHandlerInvocation(
            element_id="b", action="click", ts=1.0, hub_token="hub-a"
        )

        assert delivery.deliver([first, second]) == ((), ())  # none landed

    def test_delivered_prefix_leaves_the_buffer_before_a_stop(self) -> None:
        good, bad = object(), object()
        delivery, _ = _build(
            fd_to_client={8: good, 9: bad},
            hub_fds={"hub-a": 8},
            scene_to_owner={"s9": 9},
            send_results={bad: False},
        )
        # first routes to `good` via its declared Hub (delivered); second
        # targets the dead scene owner and blocks the line.
        first = RemoteEventHandlerInvocation(
            element_id="a", action="click", ts=1.0, hub_token="hub-a"
        )
        second = RemoteEventHandlerInvocation(
            element_id="b", action="click", scene_id="s9", ts=1.0
        )

        assert delivery.deliver([first, second]) == ((first,), ())  # only the prefix

    def test_missing_owner_socket_stops_delivery(self) -> None:
        delivery, socket_listener = _build(scene_to_owner={"s1": 7})  # fd 7 not mapped
        event = RemoteEventHandlerInvocation(
            element_id="b", action="click", scene_id="s1", ts=1.0
        )

        assert delivery.deliver([event]) == ((), ())
        socket_listener.send_to_client.assert_not_called()

    def test_spent_budget_delivers_nothing(self) -> None:
        # When the frame budget is spent, ``SocketListener.send_to_client`` returns
        # False (its deadline has passed). Delivery stops at the first refusal so
        # the caller re-holds the whole prefix for the next frame.
        sock = object()
        delivery, socket_listener = _build(
            fd_to_client={9: sock}, hub_fds={"hub-a": 9}, send_results={sock: False}
        )
        event = RemoteEventHandlerInvocation(
            element_id="b", action="click", ts=1.0, hub_token="hub-a"
        )

        assert delivery.deliver([event]) == ((), ())
        assert socket_listener.send_to_client.call_count == 1

    def test_a_menu_click_survives_its_hubs_reconnect(self) -> None:
        # The Hub is absent at the first flush -- the click is deferred and kept,
        # not dropped -- then it reconnects and the held click is delivered. This
        # is the reconnect-window case the deferral exists to close.
        hub_sock = object()
        delivery, socket_listener = _build()  # no Hubs connected yet
        buf = PendingInteractions()
        event = RemoteEventHandlerInvocation(
            element_id="m", action="menu", ts=1.0, hub_token="hub-a"
        )
        buf.admit([event], now=100.0)

        removed, dropped = delivery.deliver(buf.pending_events())
        buf.discard_delivered(removed)
        assert (removed, dropped) == ((), ())  # deferred: neither sent nor dropped
        assert [e.element_id for e in buf.pending_events()] == ["m"]  # still held

        socket_listener.fd_to_client[9] = hub_sock  # hub-a reconnects
        socket_listener.fd_for_hub_token.side_effect = {"hub-a": 9}.get

        removed, dropped = delivery.deliver(buf.pending_events())
        buf.discard_delivered(removed)
        assert removed == (event,)
        assert buf.is_empty  # delivered on reconnect, no longer held
        socket_listener.send_to_client.assert_called_once_with(hub_sock, event)

    def test_a_deferred_menu_click_ages_out_when_its_hub_never_returns(self) -> None:
        # A truly-departed Hub's click is held only for the bounded window; once
        # it ages out the buffer gives it up. A menu click latches nothing, so
        # compensating the aged-out click is a harmless no-op (it must not raise).
        delivery, socket_listener = _build()  # Hub never present
        buf = PendingInteractions(max_age=3.0)
        event = RemoteEventHandlerInvocation(
            element_id="m", action="menu", ts=1.0, hub_token="gone-hub"
        )
        buf.admit([event], now=100.0)
        removed, _dropped = delivery.deliver(buf.pending_events())
        buf.discard_delivered(removed)
        assert [e.element_id for e in buf.pending_events()] == ["m"]  # held at first

        delivery.compensate_evicted(buf.expire(now=104.0))  # past max_age

        assert buf.is_empty  # aged out once the reconnect window lapsed
        socket_listener.send_to_client.assert_not_called()


class TestCompensateEvicted:
    """Every kind that latches display-side state gives that latch up on eviction.

    An evicted interaction never reaches the Hub, so no answer for it will ever
    arrive: whatever the display latched when it fired would render forever
    against an unchanged Hub. Eviction is a rejection that never got said, and
    each kind below drops what it was holding so the next frame renders the Hub's
    value.
    """

    def test_evicted_modal_close_clears_latches(self) -> None:
        ws = WidgetState()
        ws.set(f"m{WidgetState.OPEN_SUFFIX}", 1)
        ws.set(f"m{WidgetState.DISMISS_SUFFIX}", 1)
        delivery, _ = _build(widget_state=ws)

        delivery.compensate_evicted(_lost(_evicted("modal_closed", "m")))

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

        delivery.compensate_evicted(_lost(_evicted("row_selection_changed", "t")))

        assert ws.get(f"t{WidgetState.ROW_SELECTION_PENDING_SUFFIX}") is None
        assert ws.get(f"t{WidgetState.ROW_SELECTION_HONOURED_SUFFIX}") is None

    def test_evicted_header_toggle_clears_the_pending_open_state(self) -> None:
        # The arbiter's pending slot outvotes the Hub flag for as long as it is
        # held, and only a Hub-driven operation clears it — which an evicted
        # toggle guarantees will never come. Without this the header renders the
        # user's optimistic open state against a Hub that never agreed.
        ws = WidgetState()
        ws.set(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", True)
        delivery, _ = _build(widget_state=ws)

        delivery.compensate_evicted(_lost(_evicted("header_toggled", "h")))

        assert ws.get(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is None

    def test_evicted_tab_change_clears_both_selection_slots(self) -> None:
        # The pending slot suppresses a re-fire and the honoured slot suppresses
        # the force-select that would pull the bar back, so an evicted TabChanged
        # strands the display on a tab the Hub never selected. Clearing both lets
        # the next frame force-select the Hub's active tab — without firing, since
        # an unhonoured slot reads as no user switch.
        ws = WidgetState()
        ws.set(f"tb{WidgetState.PENDING_SUFFIX}", "two")
        ws.set(f"tb{WidgetState.HONOURED_SUFFIX}", "one")
        delivery, _ = _build(widget_state=ws)

        delivery.compensate_evicted(_lost(_evicted("tab_changed", "tb")))

        assert ws.get(f"tb{WidgetState.PENDING_SUFFIX}") is None
        assert ws.get(f"tb{WidgetState.HONOURED_SUFFIX}") is None

    def test_evicted_value_commit_clears_the_optimistic_echo(self) -> None:
        # The continuous-edit arbiter honours a committed value until the Hub
        # value moves off the one observed at commit time. An evicted commit means
        # it never will, so the committed value would render forever.
        ws = WidgetState()
        ws.set(f"i{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}", "typed")
        ws.set(f"i{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}", "old")
        delivery, _ = _build(widget_state=ws)

        delivery.compensate_evicted(_lost(_evicted("value_changed", "i")))

        assert ws.get(f"i{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}") is None
        assert ws.get(f"i{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}") is None

    def test_a_lost_commit_leaves_a_live_edit_alone(self) -> None:
        # The buffer is the user's keystrokes, not optimism about the Hub: a
        # commit lost in flight must not wipe what is being typed now.
        ws = WidgetState()
        ws.set(f"i{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}", "still typing")
        ws.set(f"i{WidgetState.CONTINUOUS_EDIT_EDITING_SUFFIX}", True)
        delivery, _ = _build(widget_state=ws)

        delivery.compensate_evicted(_lost(_evicted("value_changed", "i")))

        assert ws.get(f"i{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}") == "still typing"
        assert ws.get(f"i{WidgetState.CONTINUOUS_EDIT_EDITING_SUFFIX}") is True

    def test_a_button_click_latches_nothing_and_clears_nothing(self) -> None:
        # A click's whole effect is Hub-side, so its eviction owes the display
        # nothing — and must not reach for a neighbouring widget's latch.
        ws = WidgetState()
        ws.set(f"m{WidgetState.DISMISS_SUFFIX}", 1)
        delivery, _ = _build(widget_state=ws)
        click = RemoteEventHandlerInvocation(
            element_id="m", action="click", scene_id="s1", ts=1.0
        )

        delivery.compensate_evicted(_lost(click))

        assert ws.get(f"m{WidgetState.DISMISS_SUFFIX}") == 1

    def test_scene_less_event_is_ignored(self) -> None:
        delivery, _ = _build(widget_state=None)
        # No scene_id → no widget state to revert; must not raise.
        delivery.compensate_evicted(_lost(_evicted("modal_closed", "m", scene_id=None)))


class TestSupersededEvictionRevertsNothing:
    """A live gesture keeps its latch when an older one of its kind ages out.

    The user interacts twice in quick succession and the first interaction ages
    out while the second is still in flight. Compensating the older one would
    snap the widget back to the Hub's value with a live interaction still
    awaiting its answer -- the double-step, arriving by a second route. The
    latch stands until the newer gesture is answered or is itself lost.
    """

    def test_a_superseded_header_toggle_leaves_the_pending_open_state(self) -> None:
        ws = WidgetState()
        ws.set(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", True)
        delivery, _ = _build(widget_state=ws)
        evicted, _buf = _aged_out_while_newer_held("header_toggled", "h")

        delivery.compensate_evicted(evicted)

        assert ws.get(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is True

    def test_a_superseded_tab_change_leaves_both_selection_slots(self) -> None:
        ws = WidgetState()
        ws.set(f"tb{WidgetState.PENDING_SUFFIX}", "three")
        ws.set(f"tb{WidgetState.HONOURED_SUFFIX}", "two")
        delivery, _ = _build(widget_state=ws)
        evicted, _buf = _aged_out_while_newer_held("tab_changed", "tb")

        delivery.compensate_evicted(evicted)

        assert ws.get(f"tb{WidgetState.PENDING_SUFFIX}") == "three"
        assert ws.get(f"tb{WidgetState.HONOURED_SUFFIX}") == "two"

    def test_a_superseded_value_commit_leaves_the_committed_echo(self) -> None:
        ws = WidgetState()
        ws.set(f"i{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}", "second")
        ws.set(f"i{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}", "old")
        delivery, _ = _build(widget_state=ws)
        evicted, _buf = _aged_out_while_newer_held("value_changed", "i")

        delivery.compensate_evicted(evicted)

        assert ws.get(f"i{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}") == "second"
        assert ws.get(f"i{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}") == "old"

    def test_the_newer_gesture_still_compensates_when_it_is_lost_in_turn(self) -> None:
        # The latch is not stranded: once the surviving toggle ages out too,
        # nothing is left speaking for the header and the slot is handed back.
        ws = WidgetState()
        ws.set(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", True)
        delivery, _ = _build(widget_state=ws)
        first, buf = _aged_out_while_newer_held("header_toggled", "h")
        delivery.compensate_evicted(first)

        delivery.compensate_evicted(buf.expire(now=110.0))

        assert ws.get(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is None

    def test_the_newer_gesture_delivered_leaves_the_latch_for_its_answer(self) -> None:
        # Delivery drains the buffer between the eviction and the compensation,
        # so the split must already be taken: the sent toggle is no longer held
        # while its answer is still outstanding, and the latch must survive.
        ws = WidgetState()
        ws.set(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", True)
        owner_sock = object()
        delivery, _ = _build(
            fd_to_client={7: owner_sock}, scene_to_owner={"s1": 7}, widget_state=ws
        )
        evicted, buf = _aged_out_while_newer_held("header_toggled", "h")
        removed, _dropped = delivery.deliver(buf.pending_events())
        buf.discard_delivered(removed)
        assert buf.is_empty  # the surviving toggle went to the Hub this frame

        delivery.compensate_evicted(evicted)

        assert ws.get(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is True
