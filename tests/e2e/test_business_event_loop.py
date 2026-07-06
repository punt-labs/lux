"""The standing gate: the full bidirectional business-event loop.

Runs the loop invariants (I1-I6, plus the handler-driven re-push) over
every registered scenario, then pins the recv/ask-user surface and the
trust-boundary properties the same live loop must hold for hostile input:
deny-by-default on every malformed-invocation branch, single-fire **per
injection** (a replayed frame double-fires — there is no dedup), the causal
react gate, no-subscriber publish, connection-scoped isolation, and the
container structural guard. All in-process, no socket, no GPU — Tier-2
integration.

Honest scope on replay: the harness proves the dispatch fires exactly once
**per injected invocation**. It is NOT an anti-replay defence — the same
valid invocation sent twice fires twice, because ``_hub_interaction_dispatch``
has no dedup. ``test_replayed_invocation_double_fires`` documents that
observed gap rather than asserting a defence the system lacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.tools.hub_factory import hub_element_factory

from .inspection_view import InspectionView
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
    ("event_kind", "scene_id", "value"),
    [
        ("bogus_kind", "e2e-loop-scene", True),  # unknown event kind → deny
        ("button_clicked", None, True),  # missing scene → deny
        ("value_changed", "e2e-loop-scene", "not-a-bool"),  # non-bool value → deny
    ],
    ids=["unknown-event-kind", "missing-scene", "non-bool-value-changed"],
)
def test_malformed_invocation_is_denied(
    event_kind: str, scene_id: str | None, value: object, loop_env: LoopHarness
) -> None:
    """Fail-closed: a malformed invocation reaches no handler and publishes nothing.

    A real click can never produce these; ``send_raw`` feeds the Hub
    dispatch the hostile input directly. Deny-by-default means the real
    handler stays unfired and the subscriber inbox stays empty — covering
    the unknown-``event_kind``, missing-``scene_id``, and non-bool
    ``value_changed`` deny branches of ``_hub_interaction_dispatch``.
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
            value=value,
        )
    )

    assert recorder.fire_count == 0
    assert agent.drain() == ()


def test_unresolved_element_is_denied(loop_env: LoopHarness) -> None:
    """Fail-closed: an invocation naming an unknown element reaches no handler.

    ``hub_display.resolve`` raises for the ghost id; dispatch returns early
    on the resolve-failed branch. The real target's handler stays unfired
    and the inbox stays empty.
    """
    scenario = Scenario.group_button_progress()
    agent = loop_env.agent("ghost-agent")
    recorder = agent.show(scenario)
    agent.subscribe(scenario.topic)

    loop_env.rig.send_raw(
        RemoteEventHandlerInvocation(
            element_id="ghost-element",
            action="ghost-element",
            event_kind="button_clicked",
            scene_id=scenario.scene_id,
            value=True,
        )
    )

    assert recorder.fire_count == 0
    assert agent.drain() == ()


def test_non_abc_resolved_element_is_denied(loop_env: LoopHarness) -> None:
    """Fail-closed: an invocation resolving to a legacy (non-ABC) element is denied.

    A legacy ``separator`` root is installed beside the ABC surface; the
    dispatch resolves it, finds it is not an ``Element`` ABC, and returns
    early on the non-ABC branch. The ABC target's recorder stays unfired.
    """
    scenario = Scenario.group_button_progress()
    agent = loop_env.agent("nonabc-agent")
    recorder = agent.show(scenario)
    agent.subscribe(scenario.topic)
    agent.install_extra_root(
        scenario.scene_id, {"kind": "separator", "id": "legacy-sep"}
    )

    loop_env.rig.send_raw(
        RemoteEventHandlerInvocation(
            element_id="legacy-sep",
            action="legacy-sep",
            event_kind="button_clicked",
            scene_id=scenario.scene_id,
            value=True,
        )
    )

    assert recorder.fire_count == 0
    assert agent.drain() == ()


def test_replayed_invocation_double_fires(loop_env: LoopHarness) -> None:
    """Honest anti-replay: the SAME valid invocation sent twice fires twice.

    ``_hub_interaction_dispatch`` has no dedup, so a replayed frame is a
    duplicated side effect: the handler fires twice and the topic is
    published twice. This documents the observed gap — the harness proves
    single-fire *per injection*, not replay resistance. Dedup, if warranted,
    is separate future work.
    """
    scenario = Scenario.group_button_progress()
    agent = loop_env.agent("replay-agent")
    recorder = agent.show(scenario)
    agent.subscribe(scenario.topic)
    invocation = RemoteEventHandlerInvocation(
        element_id=scenario.target_element_id,
        action=scenario.target_element_id,
        event_kind="button_clicked",
        scene_id=scenario.scene_id,
        value=True,
    )

    loop_env.rig.send_raw(invocation)
    loop_env.rig.send_raw(invocation)

    assert recorder.fire_count == 2
    assert len(agent.drain()) == 2


def test_undelivered_event_does_not_react(loop_env: LoopHarness) -> None:
    """Causal gate + no-subscriber publish: no delivery means no reaction.

    The agent subscribes to a topic the handler never publishes, so the
    handler's publish fans out to zero subscribers (``hub.publish`` no-ops
    cleanly, no exception) and the inbox stays empty. The agent's reaction
    is gated on delivery, so it must NOT react — the display-only leaf is
    unchanged, proving the loop reacts *because* the event arrived.
    """
    scenario = Scenario.group_button_progress()
    agent = loop_env.agent("gate-agent")

    observation = agent.run_subscribed_to(scenario, "topic-nobody-publishes")

    assert observation.delivered == ()
    assert observation.reacted is False
    leaf = InspectionView(observation.post_react_inspection).props(
        scenario.display_only_id
    )
    assert leaf["fraction"] == 0.0


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


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_container_exposes_interactive_target_to_injection_walk(
    scenario: Scenario,
) -> None:
    """Structural guard: the injection walk reaches every interactive target.

    The agent injects by walking ``child_elements()`` from the roots to find
    the target; a composite that failed to expose an interactive descendant
    would silently hide it from the loop gate. This mirrors the validation
    ``child_elements()`` guard: decode the surface and assert the target id
    is reachable through the same walk.
    """
    factory = hub_element_factory(ConnectionId("guard"))
    roots = [factory.element_from_dict(e) for e in scenario.wire_elements()]

    reachable = _ids_reachable_via_child_elements(roots)

    assert scenario.target_element_id in reachable


def _ids_reachable_via_child_elements(elements: list[object]) -> frozenset[str]:
    """Collect every element id reachable through the ``child_elements`` walk."""
    ids: set[str] = set()
    for element in elements:
        _collect_ids(element, ids)
    return frozenset(ids)


def _collect_ids(element: object, sink: set[str]) -> None:
    """Add ``element``'s id and recurse its ABC children into ``sink``."""
    if not isinstance(element, AbcElement):
        return
    sink.add(element.id)
    for child in element.child_elements():
        _collect_ids(child, sink)
