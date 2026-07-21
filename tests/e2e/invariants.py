"""LoopInvariants — the I1-I6 assertions plus the handler-driven re-push.

Every assertion observes the running system through the introspection
response or the real subscriber inbox — never an internal stub of the
dispatch, handler, publish, or inbox. The invariants are constructed from
a ``Scenario`` and the ``LoopObservation`` one run produced and read the
scenario's expectation fields, so adding an element means adding a
``Scenario`` value, not new assertion code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.messages.observer import ObserverMessage

from .inspection_view import InspectionView

if TYPE_CHECKING:
    from .agent import LoopObservation
    from .scenario import Scenario

__all__ = ["LoopInvariants"]


class LoopInvariants:
    """Assert the full bidirectional loop for one scenario observation."""

    _scenario: Scenario
    _obs: LoopObservation

    def __new__(cls, scenario: Scenario, observation: LoopObservation) -> Self:
        self = super().__new__(cls)
        self._scenario = scenario
        self._obs = observation
        return self

    def assert_all(self) -> None:
        """Assert every loop invariant in causal order."""
        self.assert_faithful_crossing()
        self.assert_hub_authoritative_once()
        self.assert_business_event_delivered()
        self.assert_handler_driven_repush()
        self.assert_repush_structure_intact()
        self.assert_recv_surface_is_real()
        self.assert_return_path_replica()
        self.assert_two_mechanisms_distinct()

    def assert_repush_structure_intact(self) -> None:
        """S — every re-push preserves the scene's tree shape, not just props.

        A re-push resends the scene's roots; it must never hoist a container's
        child to a top-level sibling nor duplicate an element. Each snapshot's
        ``element_paths`` must carry every id once, and neither the dispatch
        re-push nor the agent's return-path re-push may grow the root set the
        initial ``show`` established (a handler removal may shrink it — the
        dialog case — so the check is subset, not equality).

        This is the assertion the prop-only invariants missed: a flattening
        re-push left the mutated prop correct while hoisting and duplicating
        every child, and every I-check still passed.
        """
        show = InspectionView(self._obs.post_show_inspection)
        dispatch = InspectionView(self._obs.post_dispatch_inspection)
        react = InspectionView(self._obs.post_react_inspection)
        show_roots = show.root_ids()
        for label, view in (
            ("show", show),
            ("dispatch", dispatch),
            ("react", react),
        ):
            assert not view.duplicate_ids(), (
                f"{label} re-push duplicated elements {sorted(view.duplicate_ids())} "
                f"— a child was hoisted to a top-level root"
            )
            assert view.root_ids() <= show_roots, (
                f"{label} re-push grew the root set to {sorted(view.root_ids())} "
                f"beyond the shown roots {sorted(show_roots)} — a child was hoisted"
            )

    def assert_faithful_crossing(self) -> None:
        """I1 — one real-click-shaped invocation crossed the Connection."""
        crossed = self._obs.crossed
        assert len(crossed) == 1, f"expected one crossed invocation, got {len(crossed)}"
        invocation = crossed[0]
        expect = self._scenario.interaction
        assert invocation.element_id == self._scenario.target_element_id
        assert invocation.event_kind == expect.event_kind
        assert invocation.value == expect.value
        assert invocation.scene_id == self._scenario.scene_id

    def assert_hub_authoritative_once(self) -> None:
        """I2 — the real handler ran once on the Hub's authoritative copy.

        The single observable effect is single: the view-logic handler
        fired exactly once and exactly one business event was delivered —
        a double-fire would double both.
        """
        assert self._obs.recorder.fire_count == 1
        assert len(self._obs.delivered) == 1

    def assert_business_event_delivered(self) -> None:
        """I3 — a real subscriber received the published business event."""
        delivered = self._obs.delivered
        assert len(delivered) == 1
        message = delivered[0]
        assert message.topic == self._scenario.topic
        assert message.payload == self._scenario.publish.payload

    def assert_handler_driven_repush(self) -> None:
        """D — the dispatch re-push reflected the handler's Hub-side mutation.

        Reads the replica after dispatch but before any agent ``update``, so
        a mutation present here travelled ``_hub_interaction_dispatch``'s own
        re-push leg — a checkbox value flip, a dialog removal, or an
        unchanged tree — not the agent's return-path ``update``.
        """
        self._scenario.repush.assert_reflected(
            self._obs.post_show_inspection,
            self._obs.post_dispatch_inspection,
        )

    def assert_recv_surface_is_real(self) -> None:
        """I4 — the event arrived on the real inbox recv surface, not a sink.

        Every delivered item is an ``ObserverMessage`` the ``domain.hub.inbox``
        ``recv`` / ``drain_inbox`` surface yields — never a test publish-sink.
        The non-empty check stands on its own so an empty inbox fails loud
        here rather than passing a vacuous ``all(...)``.
        """
        delivered = self._obs.delivered
        assert len(delivered) == 1, f"expected one delivered message, got {delivered!r}"
        assert all(isinstance(m, ObserverMessage) for m in delivered)

    def assert_return_path_replica(self) -> None:
        """I5 — the agent reacted BECAUSE the event arrived, and the replica shows it.

        The causal chain closes here: the agent reacted only because the
        subscribed business event was delivered (``reacted`` is gated on
        delivery in ``SimulatedAgent.run``). Every react patch flipped its
        field from the pre-react value to the reacted value, present only via
        the re-push, and the display-only leaf survived the round trip (the
        container carried a mixed composition end to end).
        """
        assert self._obs.reacted, "agent must react when business event delivered"
        leaf = self._scenario.display_only_id
        pre = InspectionView(self._obs.post_dispatch_inspection)
        post = InspectionView(self._obs.post_react_inspection)
        assert pre.record(leaf)["render_path"] == "abc"
        assert post.record(leaf)["render_path"] == "abc"
        for patch in self._scenario.react:
            pre_props = pre.props(patch.element_id)
            post_props = post.props(patch.element_id)
            assert pre_props[patch.field] != patch.value, (
                f"react precondition: {patch.element_id}.{patch.field} "
                f"already equals {patch.value!r} before the reaction"
            )
            assert post_props[patch.field] == patch.value, (
                f"react: {patch.element_id}.{patch.field} "
                f"expected {patch.value!r}, got {post_props[patch.field]!r}"
            )

    def assert_two_mechanisms_distinct(self) -> None:
        """I6 — the UI-handler and pub-sub mechanisms each fired, independently.

        The view-logic recorder (element handler dispatch, D21) and the
        published topic (Hub application pub-sub) are separate paths; the
        harness asserts each and neither is used to fake the other. The
        non-empty check stands on its own so the topic membership is never
        vacuously satisfied on an empty inbox.
        """
        assert self._obs.recorder.fire_count == 1
        delivered = self._obs.delivered
        assert len(delivered) == 1, f"expected one delivered message, got {delivered!r}"
        topics = {m.topic for m in delivered}
        assert self._scenario.topic in topics
