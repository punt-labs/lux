"""HeaderOpenArbiter — the collapsing header's toggle across the re-push window.

Two levels. The first proves the arbiter as a pure function of its slot, the
analogue of the tab-bar and table arbiters' tests. The second drives the *real*
``ImGuiCollapsingHeaderRenderer`` frame by frame against a stand-in that models
ImGui's stored open state faithfully, and journals what each frame rendered:
that is where the reported defect lives, because a double-step is a property of
a sequence of frames and no single-frame assertion can see it.
"""

from __future__ import annotations

import dataclasses
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Self, cast, final

from punt_lux.display.evictions import Evictions
from punt_lux.display.interaction_delivery import InteractionDelivery
from punt_lux.display.renderers.imgui import collapsing_header as header_module
from punt_lux.display.renderers.imgui.collapsing_header import (
    ImGuiCollapsingHeaderRenderer,
)
from punt_lux.display.renderers.imgui.header_open_arbiter import HeaderOpenArbiter
from punt_lux.display.replica.widget_state import WidgetState
from punt_lux.display_client import agent_element_factory
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest

    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )


def _arbiter() -> tuple[HeaderOpenArbiter, WidgetState]:
    ws = WidgetState()
    return HeaderOpenArbiter(ws, "disclosure"), ws


# -- the arbiter as a pure function of its slot -----------------------------


def test_nothing_pending_renders_the_hub_value() -> None:
    arbiter, _ = _arbiter()
    assert arbiter.effective_open(authoritative=True) is True
    assert arbiter.effective_open(authoritative=False) is False


def test_a_pending_toggle_is_rendered_over_the_stale_hub_value() -> None:
    # THE CENTERPIECE at this level. Between the click and the Hub's confirming
    # re-push the Hub flag still reads pre-click; rendering it would snap the
    # section shut for the length of the round trip. The pending value wins.
    arbiter, _ = _arbiter()
    arbiter.note_pending(fired=True)
    assert arbiter.effective_open(authoritative=False) is True


def test_a_pending_close_is_rendered_over_a_stale_open_hub_value() -> None:
    # The same in the closing direction — the slot holds a value, not a flag.
    arbiter, _ = _arbiter()
    arbiter.note_pending(fired=False)
    assert arbiter.effective_open(authoritative=True) is False


def test_the_re_push_reset_hands_authority_back_to_the_hub() -> None:
    # The slot is per-render-session: SceneReplica resets it on every scene
    # replace, which is what stops the optimism outliving the Hub's answer.
    arbiter, ws = _arbiter()
    arbiter.note_pending(fired=True)
    ws.reset_session_slots()
    assert arbiter.effective_open(authoritative=False) is False


def test_a_removed_header_leaves_no_pending_behind() -> None:
    # A same-id header re-added later must show the Hub's declared state, not a
    # departed header's in-flight toggle.
    arbiter, ws = _arbiter()
    arbiter.note_pending(fired=True)
    ws.discard_for("disclosure")
    assert arbiter.effective_open(authoritative=False) is False


def test_one_header_s_pending_does_not_leak_into_another() -> None:
    ws = WidgetState()
    HeaderOpenArbiter(ws, "left").note_pending(fired=True)
    assert HeaderOpenArbiter(ws, "right").effective_open(authoritative=False) is False


def test_a_non_bool_in_the_slot_leaves_the_hub_in_charge() -> None:
    # The slot lives in an untyped per-scene store. Only a toggle this arbiter
    # recorded may outvote the Hub — a value of any other type is not a pending
    # toggle, however truthy, and must not hold the section open (nor, when the
    # Hub says open, shut) until the next re-push clears it.
    arbiter, ws = _arbiter()
    ws.set(f"disclosure{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", "open")
    assert arbiter.effective_open(authoritative=False) is False
    assert arbiter.effective_open(authoritative=True) is True


# -- the render journal: the real renderer over a faithful ImGui store ------


@final
class _ImGuiStore:
    """Stand in for ImGui's stored collapsing-header state.

    ImGui's own ``TreeNodeBehavior`` reads the store (which
    ``set_next_item_open`` may have just written), applies the user's click, and
    draws from the result — so a click is visible in the very frame that
    produced it, and persists into the next frame unless something writes over
    it. Both halves matter here: the first is why the click renders at once, the
    second is why writing the Hub value every frame reverts it.
    """

    _stored: bool
    _click_armed: bool
    __slots__ = ("_click_armed", "_stored")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._stored = False
        self._click_armed = False
        return self

    def arm_click(self) -> None:
        """Queue a click on the disclosure triangle for the next frame."""
        self._click_armed = True

    def set_next_item_open(self, value: bool) -> None:
        """Write the store, as ``imgui.set_next_item_open`` does."""
        self._stored = value

    def collapsing_header(self, label: str) -> bool:
        """Apply any armed click and return the state the header draws."""
        _ = label
        if self._click_armed:
            self._stored = not self._stored
            self._click_armed = False
        return self._stored


@final
class _FactoryDouble:
    """The slice of ``ImGuiRendererFactory`` the header adapter reaches for."""

    _widget_state: WidgetState
    __slots__ = ("_widget_state",)

    def __new__(cls, widget_state: WidgetState) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        return self

    @property
    def widget_state(self) -> WidgetState:
        """Return the per-scene widget state the arbiter keys into."""
        return self._widget_state

    def apply_tooltip(self, elem: object) -> None:
        """No-op — the tooltip pass is covered in ``test_imgui_adapters``."""
        _ = elem


@final
class _SceneReplicaDouble:
    """The one lookup ``compensate_evicted`` makes of the scene manager."""

    _widget_state: WidgetState
    __slots__ = ("_widget_state",)

    def __new__(cls, widget_state: WidgetState) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        return self

    def widget_state_for(self, scene_id: str) -> WidgetState:
        """Return the per-scene widget state the compensation clears."""
        _ = scene_id
        return self._widget_state


@final
class _HeaderRig:
    """One header on the Display tier, driven a frame at a time.

    Holds what a running display holds — the ImGui store, the per-scene widget
    state, the replica whose handlers are wrapped for remote dispatch — and
    records the open state each frame rendered plus every invocation that
    crossed to the Hub.
    """

    _store: _ImGuiStore
    _state: WidgetState
    _elem: CollapsingHeaderElement
    _renderer: ImGuiCollapsingHeaderRenderer
    _sent: list[RemoteEventHandlerInvocation]
    _journal: list[bool]
    __slots__ = ("_elem", "_journal", "_renderer", "_sent", "_state", "_store")

    def __new__(cls, monkeypatch: pytest.MonkeyPatch, *, open: bool = False) -> Self:
        self = super().__new__(cls)
        self._store = _ImGuiStore()
        monkeypatch.setattr(header_module, "imgui", self._store)
        self._state = WidgetState()
        self._elem = _display_replica(open=open)
        self._sent = []
        self._elem.wrap_handlers_for_remote(self._sent.append)
        self._renderer = ImGuiCollapsingHeaderRenderer(
            self._elem, cast("Any", _FactoryDouble(self._state))
        )
        # Seeded with ImGui's own default for a header it has never drawn, so
        # ``steps`` counts the first frame's transition too — the cold push
        # driving a declared-open header over that default is a real step.
        self._journal = [False]
        return self

    @property
    def journal(self) -> tuple[bool, ...]:
        """Return the open state every frame so far rendered, in order."""
        return tuple(self._journal[1:])

    @property
    def steps(self) -> int:
        """Return how many times the rendered state visibly changed."""
        return sum(1 for before, after in pairwise(self._journal) if before != after)

    @property
    def fires(self) -> int:
        """Return how many interactions crossed to the Hub."""
        return len(self._sent)

    def frame(self, *, click: bool = False) -> bool:
        """Render one frame, optionally with the user clicking during it."""
        if click:
            self._store.arm_click()
        shown = self._renderer.begin()
        self._journal.append(shown)
        return shown

    def evict(self) -> None:
        """Age the click's interaction out of the pending buffer, as the display does.

        The buffer hands an interaction it could not deliver to
        ``InteractionDelivery.compensate_evicted``, and this drives that real
        method with the invocation the click really sent — so the wire
        ``event_kind`` the renderer stamped is the one the compensation is looked
        up by. The scene id is the one the display's ``_emit_event`` stamps on the
        way out; the socket server is never reached on this path.
        """
        lost = dataclasses.replace(self._sent[-1], scene_id="scene")
        InteractionDelivery(
            socket_server=cast("Any", None),
            scenes=cast("Any", _SceneReplicaDouble(self._state)),
        ).compensate_evicted(Evictions.of([lost], ()))

    def repush(self, *, open: bool) -> None:
        """Apply the Hub's answer, as a whole-scene re-push would.

        The replica takes the Hub's value and ``SceneReplica`` resets the
        per-render-session slots — the two halves of a scene replace that this
        arbiter's correctness rests on.
        """
        self._elem.apply_patch({"open": open})
        self._state.reset_session_slots()


def _display_replica(*, open: bool) -> CollapsingHeaderElement:
    """Return a decoded header as the Display holds it — real codec, real handlers."""
    wire: Mapping[str, object] = CollapsingHeaderElement(
        id="disclosure",
        label="Details",
        open=open,
        children=(TextElement(id="body", content="hidden"),),
    ).to_dict()
    elem = agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))
    assert isinstance(elem, CollapsingHeaderElement)
    return elem


def test_one_click_yields_exactly_one_visible_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE REPORTED DEFECT. Before the arbiter, the frame after the click wrote
    # the Hub's still-pre-click value back into ImGui's store and the section
    # snapped shut, then the confirming re-push opened it again: the journal
    # read (True, False, False, True) — one click, three rendered states, two
    # steps the user never asked for. It must now hold the click all the way
    # through to the Hub's answer.
    rig = _HeaderRig(monkeypatch)

    rig.frame(click=True)
    rig.frame()
    rig.frame()

    assert rig.journal == (True, True, True), "the toggle must survive the round trip"
    assert rig.steps == 1, "one click must move the rendered state exactly once"


def test_the_click_frame_opens_the_section_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The other half of "exactly one step": the step happens at the click, not
    # a round trip later. Suppressing the local apply would also give one step,
    # at the cost of a visible lag on every toggle.
    rig = _HeaderRig(monkeypatch)

    assert rig.frame() is False
    assert rig.frame(click=True) is True


def test_the_window_fires_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every frame between the click and the re-push reports the clicked state.
    # Comparing that against the raw Hub flag would fire on each one — a fire
    # storm across the latency window, and a fire -> re-push -> fire loop.
    rig = _HeaderRig(monkeypatch)

    rig.frame(click=True)
    for _ in range(5):
        rig.frame()

    assert rig.fires == 1


def test_the_ratifying_re_push_moves_nothing_and_fires_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Hub agrees. Its echo must be invisible: the section is already open,
    # and honouring the now-matching Hub value must not read as a fresh toggle.
    rig = _HeaderRig(monkeypatch)

    rig.frame(click=True)
    rig.frame()
    rig.repush(open=True)
    rig.frame()
    rig.frame()

    assert rig.journal == (True, True, True, True)
    assert rig.steps == 1, "the click's own step, and nothing from the echo"
    assert rig.fires == 1


def test_a_rejected_toggle_converges_back_to_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Hub disagrees — it re-pushes the pre-click value. The display must
    # give up its optimistic view rather than hold a state the Hub denies.
    # This is the one case where a second visible step is correct.
    rig = _HeaderRig(monkeypatch)

    rig.frame(click=True)
    rig.repush(open=False)
    rig.frame()

    assert rig.journal == (True, False), "the Hub wins once it has spoken"
    assert rig.steps == 2, "the click's step, then the Hub's corrective one"
    assert rig.fires == 1, "converging must not fire an interaction back"


def test_an_evicted_toggle_hands_the_header_back_to_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The interaction aged out of the pending buffer, so the Hub never heard the
    # toggle and no re-push will ever ratify or reject it. Without compensation
    # the pending slot outvotes the Hub flag for the life of the scene and the
    # section stays open against a Hub that says closed. Eviction is a rejection
    # that never got said, so it converges the same way one does — and by a
    # different path from the re-push above, which the tests around this one pin.
    rig = _HeaderRig(monkeypatch)

    rig.frame(click=True)
    rig.frame()
    rig.evict()
    rig.frame()

    assert rig.journal == (True, True, False), "the Hub wins an answer never given"
    assert rig.fires == 1, "converging must not fire an interaction back"


def test_a_header_pushed_open_cold_opens_on_its_first_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ImGui defaults a header it has never seen to closed, so the declared value
    # has to be driven over that default. Honouring the Hub only when its value
    # *changes* would leave this header shut forever.
    rig = _HeaderRig(monkeypatch, open=True)

    assert rig.frame() is True
    assert rig.fires == 0, "rendering the declared state is not a user toggle"


def test_an_agent_driven_change_moves_the_display_without_firing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The agent closes the section from the Hub side. The display follows, and
    # the echo must not come back as an interaction.
    rig = _HeaderRig(monkeypatch)

    rig.frame(click=True)
    rig.repush(open=True)
    rig.frame()
    rig.repush(open=False)

    assert rig.frame() is False
    assert rig.fires == 1, "only the user's click fired"


def test_a_second_click_after_the_re_push_fires_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fire suppression is scoped to one window, not to the header's lifetime:
    # once the Hub has answered, the next click must be heard.
    rig = _HeaderRig(monkeypatch)

    rig.frame(click=True)
    rig.repush(open=True)
    rig.frame(click=True)

    assert rig.journal == (True, False)
    assert rig.fires == 2
