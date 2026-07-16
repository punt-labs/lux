"""Level-4 e2e: a renderer-sanitized commit is always Hub-acceptable.

The renderer's commit guard (``elem.sanitized``) and the Hub's ``apply_patch``
re-check must never disagree: whatever the renderer fires, ``apply_patch`` must
accept. This drives the **real** loop — the production ``InputNumberRenderer``
paints a windowless Display replica through a scripted imgui, the replica's own
wrapped ``ValueChanged`` handler crosses the interaction over the shipped
``InMemoryConnection`` to the production Hub dispatch, and the Hub's built-in
state-sync handler applies the fired value to its authoritative copy.

Two entries exercise both divergence classes: an over-max entry (round 1) and a
non-finite overflow on a field with no bound to clamp it (round 2). For each the
renderer fires a finite, in-range value the Hub ``apply_patch`` accepts with no
raise and no swallow, and the re-push shows the sanitized value on the Display.
A future change that widened what the renderer fires but not what ``apply_patch``
accepts would leave a swallowed reject here — the Hub value would not advance and
this test would fail.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

import pytest

from punt_lux.display.renderers import input_number_renderer
from punt_lux.display.renderers.input_number_renderer import InputNumberRenderer
from punt_lux.domain.hub import hub_display
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.scene.widget_state import WidgetState
from punt_lux.tools.hub_factory import hub_element_factory

from .inspection_view import InspectionView

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )

    from .conftest import LoopHarness

pytestmark = pytest.mark.integration

_SCENE = "e2e-sanitize-scene"
_CONN = "sanitize-agent"


@dataclass(frozen=True, slots=True)
class _Frame:
    """One scripted imgui frame: the value entered and the item-state flags."""

    edited: float | None
    active: bool
    committed: bool


class _FakeImgui:
    """Fake imgui replaying one scripted frame per ``input_float`` call."""

    _frames: list[_Frame]
    _index: int
    _current: _Frame

    def __new__(cls, *frames: _Frame) -> Self:
        self = super().__new__(cls)
        self._frames = list(frames)
        self._index = 0
        self._current = frames[0]
        return self

    def input_float(
        self, _label: str, current: float, _step: float, _fast: float, _fmt: str
    ) -> tuple[bool, float]:
        frame = self._frames[self._index]
        self._index += 1
        self._current = frame
        value = current if frame.edited is None else frame.edited
        return (frame.edited is not None, value)

    def input_int(
        self, _label: str, current: int, _step: int, _fast: int
    ) -> tuple[bool, int]:
        changed, value = self.input_float(_label, float(current), 0.0, 0.0, "")
        return (changed, int(value))

    def is_item_active(self) -> bool:
        return self._current.active

    def is_item_deactivated_after_edit(self) -> bool:
        return self._current.committed


def _install(
    rig_scene: str, hub_roots: Sequence[DomainElement], harness: LoopHarness
) -> None:
    """Install the authoritative Hub scene and push its Display replica."""
    hub_display.replace_scene(ConnectionId(_CONN), SceneId(rig_scene), hub_roots)
    harness.rig.push_scene(rig_scene, hub_roots)


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    element_id: str,
    entry: float,
    harness: LoopHarness,
) -> tuple[RemoteEventHandlerInvocation, ...]:
    """Paint one edit+commit gesture on the replica and cross it to the Hub."""
    fake = _FakeImgui(
        _Frame(edited=entry, active=True, committed=False),
        _Frame(edited=None, active=False, committed=True),
    )
    monkeypatch.setattr(input_number_renderer, "imgui", fake)
    replica = harness.rig.resolve_replica(element_id)
    assert isinstance(replica, InputNumberElement)
    renderer = InputNumberRenderer(WidgetState())
    renderer.render(replica)  # editing: buffer set to the sanitized entry
    renderer.render(replica)  # deactivate: fires the sanitized ValueChanged
    return harness.rig.cross()


def _wire(
    element_id: str, *, min_bound: float | None, max_bound: float | None
) -> dict[str, object]:
    """Return an input_number wire dict starting at a valid value of 5.0."""
    return {
        "kind": "input_number",
        "id": element_id,
        "label": element_id,
        "value": 5.0,
        "min": min_bound,
        "max": max_bound,
    }


def test_over_max_entry_is_sanitized_and_hub_accepts(
    loop_env: LoopHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 1: an over-max entry fires the clamped bound, which the Hub accepts."""
    factory = hub_element_factory(ConnectionId(_CONN))
    wire = _wire("bounded", min_bound=0.0, max_bound=100.0)
    hub_elem = factory.element_from_dict(wire)
    assert isinstance(hub_elem, InputNumberElement)
    _install(_SCENE, [hub_elem], loop_env)

    crossed = _drive(monkeypatch, "bounded", 150.0, loop_env)

    assert len(crossed) == 1
    assert crossed[0].value == 100.0  # clamped to max before it ever crossed
    # apply_patch accepted a changed value: the Hub copy advanced, nothing swallowed.
    assert hub_elem.value == 100.0
    shown = InspectionView(loop_env.rig.inspect(_SCENE)).props("bounded")
    assert shown["value"] == 100.0


def test_non_finite_entry_is_sanitized_and_hub_accepts(
    loop_env: LoopHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 2: a ``+inf`` entry on a ``max=None`` field fires a finite value.

    Plain clamping left ``+inf`` in place here; the Hub would reject it on
    finiteness, ``fire`` would swallow the raise, and the Hub value would never
    advance. sanitized drops the gesture for the validated value, so the crossed
    value is finite and ``apply_patch`` accepts it.
    """
    factory = hub_element_factory(ConnectionId(_CONN))
    hub_elem = factory.element_from_dict(_wire("open", min_bound=0.0, max_bound=None))
    assert isinstance(hub_elem, InputNumberElement)
    _install(_SCENE, [hub_elem], loop_env)

    crossed = _drive(monkeypatch, "open", math.inf, loop_env)

    assert len(crossed) == 1
    value = crossed[0].value
    assert isinstance(value, float) and math.isfinite(value)  # never ±inf
    assert value == 5.0  # dropped to the element's own validated value
    # apply_patch accepted the finite value on the Hub copy — no raise, no swallow.
    assert hub_elem.value == 5.0
    shown = InspectionView(loop_env.rig.inspect(_SCENE)).props("open")
    assert shown["value"] == 5.0
