"""The standing gate: the full bidirectional business-event loop.

Runs the loop invariants (I1-I6) over every registered scenario, then
pins the recv/ask-user surface and three trust-boundary properties the
same live loop must hold for a hostile input: fail-closed on a malformed
invocation, exactly-once as an anti-replay property, and connection-scoped
isolation. All in-process, no socket, no GPU — Tier-2 integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

from .invariants import LoopInvariants
from .scenario import SCENARIOS, Scenario

if TYPE_CHECKING:
    from .conftest import LoopHarness

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_business_event_loop(scenario: Scenario, loop_env: LoopHarness) -> None:
    """One migrated surface round-trips the whole loop; every invariant holds."""
    agent = loop_env.agent("loop-agent")
    observation = agent.run(scenario)
    LoopInvariants(scenario, observation).assert_all()


def test_recv_surface_delivers_business_event(loop_env: LoopHarness) -> None:
    """I4 — the business event is consumable on the real ``recv`` surface."""
    scenario = Scenario.group_button_progress()
    agent = loop_env.agent("recv-agent")
    agent.show(scenario)
    agent.subscribe(scenario.topic)
    agent.inject(scenario.target_element_id)

    message = agent.recv(timeout=1.0)

    assert message is not None
    assert message.topic == scenario.topic


@pytest.mark.parametrize(
    "event_kind, scene_id",
    [
        ("bogus_kind", "e2e-loop-scene"),  # unknown event kind → deny
        ("button_clicked", None),  # missing scene → deny
    ],
    ids=["unknown-event-kind", "missing-scene"],
)
def test_malformed_invocation_is_denied(
    event_kind: str, scene_id: str | None, loop_env: LoopHarness
) -> None:
    """Fail-closed: a malformed invocation reaches no handler and publishes nothing.

    A real click can never produce these; ``send_raw`` feeds the Hub
    dispatch the hostile input directly. Deny-by-default means the real
    handler stays unfired and the subscriber inbox stays empty.
    """
    scenario = Scenario.group_button_progress()
    agent = loop_env.agent("denied-agent")
    recorder = agent.show(scenario)
    agent.subscribe(scenario.topic)

    loop_env.rig.send_raw(
        RemoteEventHandlerInvocation(
            element_id=scenario.target_element_id,
            action=scenario.target_element_id,
            event_kind=event_kind,
            scene_id=scene_id,
            value=True,
        )
    )

    assert recorder.fire_count == 0
    assert agent.drain() == ()


def test_click_publishes_only_to_owning_connection(loop_env: LoopHarness) -> None:
    """Connection-scoped isolation on the live loop.

    A second connection subscribed to the same topic name — in its own
    scope — receives nothing from the first connection's injected click.
    Fan-out never crosses connection scope.
    """
    scenario = Scenario.group_button_progress()
    owner = loop_env.agent("owner-agent")
    eavesdropper = loop_env.agent("eavesdropper-agent")
    owner.show(scenario)
    owner.subscribe(scenario.topic)
    eavesdropper.subscribe(scenario.topic)

    owner.inject(scenario.target_element_id)

    assert len(owner.drain()) == 1
    assert eavesdropper.drain() == ()
