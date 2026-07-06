"""LoopInvariants — the I1-I6 assertions, expressed once per the design.

Every assertion observes the running system through the introspection
response or the real subscriber inbox — never an internal stub of the
dispatch, handler, publish, or inbox. The invariants are constructed from
a ``Scenario`` and the ``LoopObservation`` one run produced, so adding an
element means adding a ``Scenario`` value, not new assertion code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from collections.abc import Mapping

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
        self.assert_recv_surface_is_real()
        self.assert_return_path_replica()
        self.assert_two_mechanisms_distinct()

    def assert_faithful_crossing(self) -> None:
        """I1 — one real-click-shaped invocation crossed the Connection."""
        crossed = self._obs.crossed
        assert len(crossed) == 1, f"expected one crossed invocation, got {len(crossed)}"
        invocation = crossed[0]
        assert invocation.element_id == self._scenario.target_element_id
        assert invocation.event_kind == "button_clicked"
        assert invocation.value is True
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
        assert message.payload == {}

    def assert_recv_surface_is_real(self) -> None:
        """I4 — the event arrived on the real inbox recv surface, not a sink.

        Every delivered item is an ``ObserverMessage`` the ``tools.inbox``
        ``recv`` / ``drain_inbox`` surface yields — never a test publish-sink.
        """
        assert all(isinstance(m, ObserverMessage) for m in self._obs.delivered)

    def assert_return_path_replica(self) -> None:
        """I5 — after the agent reacted, the re-pushed replica reflects it.

        The display-only leaf is present both before and after (the
        container round-tripped a mixed composition), and its field flipped
        from the pre-react value to the reacted value only via the re-push.
        """
        leaf = self._scenario.display_only_id
        pre = self._record(self._obs.pre_react_inspection, leaf)
        post = self._record(self._obs.post_react_inspection, leaf)
        assert pre["render_path"] == "abc"
        assert post["render_path"] == "abc"
        react = self._scenario.react
        pre_props = cast("Mapping[str, object]", pre["props"])
        post_props = cast("Mapping[str, object]", post["props"])
        assert pre_props[react.field] != react.value
        assert post_props[react.field] == react.value

    def assert_two_mechanisms_distinct(self) -> None:
        """I6 — the UI-handler and pub-sub mechanisms each fired, independently.

        The view-logic recorder (element handler dispatch, D21) and the
        published topic (Hub application pub-sub) are separate paths; the
        harness asserts each and neither is used to fake the other.
        """
        assert self._obs.recorder.fire_count == 1
        topics = {m.topic for m in self._obs.delivered}
        assert self._scenario.topic in topics

    def _record(
        self, inspection: dict[str, object], element_id: str
    ) -> Mapping[str, object]:
        """Return the ``element_paths`` record for ``element_id`` or raise."""
        paths = cast("list[Mapping[str, object]]", inspection["element_paths"])
        for record in paths:
            if record["id"] == element_id:
                return record
        msg = f"element {element_id!r} absent from inspect_scene element_paths"
        raise AssertionError(msg)
