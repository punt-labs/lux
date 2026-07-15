"""InputTextRenderer + InputTextArbiter under the commit-echo rule.

The ``imgui.input_text`` call needs a live GL context, so the renderer tests
drive ``render`` through a fake imgui that records the buffer handed to the
widget and returns a scripted per-frame ``(changed, text)`` plus the
``is_item_active`` / ``is_item_deactivated_after_edit`` item-state flags. The
honour-or-defer decision itself is the pure ``InputTextArbiter``, tested without
imgui.

Five invariants of a controlled text input over Hub latency, each
fidelity-checked against the naive implementation it must beat:

- HONOUR-WHEN-IDLE — while the field is idle an agent-driven ``value`` change
  reaches the rendered buffer (a seed-once buffer would keep the stale value).
- DEFER-WHILE-EDITING / NO-CLOBBER — while the field is active a Hub-driven
  ``value`` does NOT overwrite the buffer and live typing survives
  (honour-every-frame would clobber it — the pipelined-edits bug).
- COMMIT-ON-IDLE — deactivating after an edit fires exactly one ``ValueChanged``
  carrying the final text.
- NO-KEYSTROKE-FIRE — nothing fires while the field is merely active/typing
  (fire-per-keystroke would emit one event per character).
- REFOCUS-DURABILITY — through the echo-latency window (a committed value in
  flight while ``elem.value`` still holds the pre-echo value) the field honours
  the committed value locally: a re-focus without editing shows what was just
  committed, and a further edit builds on that committed base, not on the stale
  pre-echo value. Defer-on-focus (the old code) and defer-on-first-edit while
  honouring the raw Hub value (the tempting incomplete fix) both lose it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers import input_text_renderer
from punt_lux.display.renderers.imgui.input_text_selection import InputTextArbiter
from punt_lux.display.renderers.input_text_renderer import InputTextRenderer
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest


@dataclass(frozen=True, slots=True)
class _Frame:
    """One scripted imgui frame.

    ``typed`` is the text the user entered this frame — ``None`` means the user
    did not edit, so imgui echoes the buffer it was handed (the real binding's
    behaviour). ``active`` and ``committed`` are the item-state flags queried
    after the widget is submitted.
    """

    typed: str | None
    active: bool
    committed: bool


class _FakeImgui:
    """Fake imgui returning one scripted ``_Frame`` per ``input_text`` call.

    ``recorded`` is the sequence of buffers ``render`` handed to the widget —
    the honour/defer evidence.
    """

    recorded: list[str]
    _frames: list[_Frame]
    _index: int
    _current: _Frame

    def __new__(cls, *frames: _Frame) -> Self:
        self = super().__new__(cls)
        self.recorded = []
        self._frames = list(frames)
        self._index = 0
        self._current = frames[0]
        return self

    def input_text_with_hint(
        self, _label: str, _hint: str, current: str
    ) -> tuple[bool, str]:
        self.recorded.append(current)
        frame = self._frames[self._index]
        self._index += 1
        self._current = frame
        text = current if frame.typed is None else frame.typed
        return (frame.typed is not None, text)

    def is_item_active(self) -> bool:
        return self._current.active

    def is_item_deactivated_after_edit(self) -> bool:
        return self._current.committed


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(input_text_renderer, "imgui", fake)


def _input(*, value: str = "", hint: str = "") -> InputTextElement:
    return InputTextElement(id="it", label="Name", value=value, hint=hint)


# -- the arbiter: the pure honour-or-defer decision ------------------------


class TestArbiterResolve:
    def test_idle_resolves_to_the_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: a fresh (idle) field renders the Hub value.
        arb = InputTextArbiter(WidgetState(), "it")
        assert arb.resolve("abc") == "abc"

    def test_idle_tracks_the_latest_hub_value(self) -> None:
        # HONOUR-WHEN-IDLE: each idle frame honours the current Hub value, so an
        # agent-driven change is picked up without any per-field bookkeeping.
        arb = InputTextArbiter(WidgetState(), "it")
        assert arb.resolve("abc") == "abc"
        assert arb.resolve("xyz") == "xyz"

    def test_editing_defers_to_the_local_buffer(self) -> None:
        # NO-CLOBBER: once a frame has observed a real edit, a Hub-driven value
        # is ignored — the in-progress buffer wins.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.observe(edited=True, text="hel")
        assert arb.resolve("ZZZ") == "hel"
        assert arb.resolve("ZZZ") == "hel"

    def test_editing_keeps_a_cleared_field_empty(self) -> None:
        # A user who clears the field is editing an empty buffer — distinct from
        # an idle field, which would fall back to the Hub value.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.observe(edited=True, text="")
        assert arb.resolve("hub") == ""

    def test_focus_without_edit_keeps_honouring(self) -> None:
        # HONOUR-DISCIPLINE: an active frame with no real edit does not begin
        # deferring — the field still honours the Hub, so an echo can reach it.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.observe(edited=False, text="abc")
        assert arb.resolve("xyz") == "xyz"

    def test_release_returns_to_honouring_the_hub(self) -> None:
        arb = InputTextArbiter(WidgetState(), "it")
        arb.observe(edited=True, text="draft")
        arb.release()
        assert arb.resolve("hub") == "hub"

    def test_slots_are_id_scoped(self) -> None:
        ws = WidgetState()
        InputTextArbiter(ws, "a").observe(edited=True, text="aaa")
        assert InputTextArbiter(ws, "a").resolve("x") == "aaa"
        assert InputTextArbiter(ws, "b").resolve("y") == "y"


class TestArbiterCommitEcho:
    def test_commit_is_honoured_until_the_hub_value_moves(self) -> None:
        # REFOCUS-DURABILITY at the arbiter: after commit, an idle frame whose
        # Hub value is still the pre-echo value renders the committed value —
        # the optimistic echo — not the stale Hub value.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.commit("hello", hub_value="")  # committed "hello"; Hub still ""
        assert arb.resolve("") == "hello"  # pre-echo window: honour committed
        assert arb.resolve("") == "hello"  # still pending

    def test_commit_record_clears_once_the_echo_arrives(self) -> None:
        # Once the Hub value moves off the commit-time value (the echo, or an
        # agent override), the record clears and the field honours the Hub.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.commit("hello", hub_value="")
        assert arb.resolve("hello") == "hello"  # echo landed: Hub == committed
        assert arb.resolve("other") == "other"  # record gone: honour the Hub

    def test_editing_wins_over_a_pending_commit(self) -> None:
        # A live edit still beats the commit-echo record: the buffer is
        # authoritative while editing, whatever the pending committed value.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.commit("hello", hub_value="")
        arb.observe(edited=True, text="fresh")
        assert arb.resolve("") == "fresh"

    def test_agent_override_mid_window_drops_the_committed_value(self) -> None:
        # AGENT-OVERRIDE-MID-WINDOW: the commit-hub marker is load-bearing.
        # resolve honours the committed value only while the Hub still holds the
        # value observed AT COMMIT TIME; it does not key off "hub != committed".
        # Commit "v1" while the Hub holds a DISTINCT pre-echo "old" (not ""):
        # the window honours "v1" as long as the Hub reads "old", but an agent
        # override that drives the Hub to a THIRD value drops the committed value
        # and honours the Hub. A wrong impl comparing hub against committed would
        # keep returning "v1" here (the override differs from committed too) and
        # still pass every test that commits with hub_value="".
        arb = InputTextArbiter(WidgetState(), "it")
        arb.commit("v1", hub_value="old")
        assert arb.resolve("old") == "v1"  # window open, Hub still pre-echo "old"
        assert arb.resolve("v2") == "v2"  # override to a third value: honour Hub

    def test_commit_value_equal_to_current_hub_persists_then_clears(self) -> None:
        # BOUNDARY commit(x, hub_value=x): committed and commit-hub coincide. The
        # record is still live and honoured while the Hub reads x, and clears on
        # the first Hub move to a different value. The output "x" is identical
        # whether the record is present or already forgotten, so the record slot
        # is read directly to prove it persisted through the equal-value frames
        # and that _forget_commit fired exactly on the move.
        ws = WidgetState()
        arb = InputTextArbiter(ws, "it")
        committed_key = f"it{WidgetState.INPUT_COMMITTED_SUFFIX}"
        arb.commit("same", hub_value="same")
        assert arb.resolve("same") == "same"  # committed == Hub: honour, record live
        assert ws.get(committed_key) == "same"  # record persists
        assert arb.resolve("same") == "same"  # still live, still honoured
        assert ws.get(committed_key) == "same"
        assert arb.resolve("other") == "other"  # Hub moved off: honour the Hub
        assert ws.get(committed_key) is None  # _forget_commit fired on the move


# -- fidelity: the naive implementations each invariant must beat ----------


class _HonourEveryFrameArbiter:
    """Naive: render the Hub value every frame, ignoring that the user edits."""

    def resolve(self, hub_value: str) -> str:
        return hub_value

    def observe(self, *, edited: bool, text: str) -> None:
        _ = (edited, text)

    def release(self) -> None:
        return None


class _SeedOnceArbiter:
    """Naive: seed the buffer once; a later idle Hub drive is lost."""

    _state: WidgetState
    _key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._key = element_id
        return self

    def resolve(self, hub_value: str) -> str:
        return str(self._state.ensure(self._key, hub_value))


class _DeferOnFocusArbiter:
    """Naive: defer on mere focus and honour the raw Hub — the old code.

    ``observe`` ignores ``edited`` and snapshots the buffer on any active frame
    (deferring begins on focus); ``resolve`` returns the raw Hub value when
    idle; ``commit`` records nothing (no optimistic echo). A re-focus during the
    echo-latency window snapshots the stale pre-echo value as the buffer.
    """

    _state: WidgetState
    _buffer_key: str
    _editing_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._buffer_key = element_id
        self._editing_key = f"{element_id}{WidgetState.INPUT_EDITING_SUFFIX}"
        return self

    def resolve(self, hub_value: str) -> str:
        if self._state.get(self._editing_key, default=False) is True:
            return self._state.get_str(self._buffer_key)
        return hub_value

    def observe(self, *, edited: bool, text: str) -> None:
        _ = edited
        self._state.set(self._editing_key, value=True)
        self._state.set(self._buffer_key, text)

    def commit(self, text: str, hub_value: str) -> None:
        _ = (text, hub_value)

    def release(self) -> None:
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)


class _RawHonourArbiter:
    """Naive: defer after the first real edit, but honour the raw Hub value.

    The tempting incomplete fix — ``observe`` gates on ``edited`` (so it never
    defers on mere focus), but ``resolve`` returns the raw Hub value when idle
    and ``commit`` records nothing. A keystroke or re-focus during the window
    still builds on the stale pre-echo value; the model proved this loses the
    committed value via the type-before-echo route.
    """

    _state: WidgetState
    _buffer_key: str
    _editing_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._buffer_key = element_id
        self._editing_key = f"{element_id}{WidgetState.INPUT_EDITING_SUFFIX}"
        return self

    def resolve(self, hub_value: str) -> str:
        if self._state.get(self._editing_key, default=False) is True:
            return self._state.get_str(self._buffer_key)
        return hub_value

    def observe(self, *, edited: bool, text: str) -> None:
        if edited or self._state.get(self._editing_key, default=False) is True:
            self._state.set(self._editing_key, value=True)
            self._state.set(self._buffer_key, text)

    def commit(self, text: str, hub_value: str) -> None:
        _ = (text, hub_value)

    def release(self) -> None:
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)


class TestArbiterFidelity:
    def test_honour_every_frame_clobbers_live_typing(self) -> None:
        # NO-CLOBBER fidelity: the honour-every-frame naive lets a stale Hub
        # value overwrite the buffer mid-edit; the real arbiter defers.
        naive = _HonourEveryFrameArbiter()
        naive.observe(edited=True, text="hel")
        assert naive.resolve("stale") == "stale"  # clobbered — the bug

        real = InputTextArbiter(WidgetState(), "it")
        real.observe(edited=True, text="hel")
        assert real.resolve("stale") == "hel"  # deferred — the fix

    def test_seed_once_ignores_a_later_idle_hub_drive(self) -> None:
        # HONOUR-WHEN-IDLE fidelity: the seed-once naive keeps the first value;
        # the real arbiter re-honours the current Hub value every idle frame.
        naive = _SeedOnceArbiter(WidgetState(), "it")
        assert naive.resolve("abc") == "abc"
        assert naive.resolve("xyz") == "abc"  # stale — the bug

        real = InputTextArbiter(WidgetState(), "it")
        assert real.resolve("abc") == "abc"
        assert real.resolve("xyz") == "xyz"  # honoured — the fix


# -- the renderer: honour idle, defer editing, commit once -----------------


class TestRendererHonour:
    def test_idle_frames_track_the_hub_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-WHEN-IDLE through the real paint seam: two idle re-push frames
        # with different values; the buffer handed to imgui tracks each.
        fake = _FakeImgui(
            _Frame(typed=None, active=False, committed=False),
            _Frame(typed=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(_input(value="abc"))
        renderer.render(_input(value="xyz"))

        assert fake.recorded == ["abc", "xyz"]


class TestRendererDefer:
    def test_hub_drive_while_editing_does_not_clobber(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NO-CLOBBER through the paint seam: the user types "hel" (frame 1), then
        # a Hub re-push carries value="ZZZ" while the field is still active
        # (frame 2). The buffer handed to imgui stays "hel", not "ZZZ".
        fake = _FakeImgui(
            _Frame(typed="hel", active=True, committed=False),
            _Frame(typed=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(_input(value=""))
        renderer.render(_input(value="ZZZ"))

        assert fake.recorded == ["", "hel"]

    def test_focus_without_editing_still_honours_a_hub_drive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR-DISCIPLINE through the seam: an active frame with no edit
        # (frame 1) does not begin deferring, so a Hub re-push (frame 2) still
        # reaches the buffer. Deferring on focus would freeze it at "abc".
        fake = _FakeImgui(
            _Frame(typed=None, active=True, committed=False),
            _Frame(typed=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(_input(value="abc"))
        renderer.render(_input(value="xyz"))

        assert fake.recorded == ["abc", "xyz"]


class TestRendererCommit:
    def test_deactivate_after_edit_fires_once_with_the_final_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # COMMIT-ON-IDLE: typing frames fire nothing; the blur frame fires
        # exactly one ValueChanged carrying the accumulated text.
        fake = _FakeImgui(
            _Frame(typed="hello", active=True, committed=False),
            _Frame(typed=None, active=False, committed=True),
        )
        _install(monkeypatch, fake)
        elem = _input(value="")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(elem)
        assert fired == []  # typing frame does not fire

        renderer.render(elem)
        assert len(fired) == 1
        assert fired[0].value == "hello"
        assert fired[0].element_id == "it"

    def test_no_fire_while_merely_typing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # NO-KEYSTROKE-FIRE: three active/typing frames, no deactivation — the
        # renderer fires nothing until the edit commits.
        fake = _FakeImgui(
            _Frame(typed="h", active=True, committed=False),
            _Frame(typed="he", active=True, committed=False),
            _Frame(typed="hel", active=True, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _input(value="")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(elem)
        renderer.render(elem)
        renderer.render(elem)

        assert fired == []


class TestRendererPostCommit:
    def test_idle_after_commit_shows_the_committed_value_until_the_echo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # POST-COMMIT LATENCY (optimistic echo): type (active) -> blur/commit
        # (deactivate-after-edit, one fire) -> idle frames while elem.value still
        # holds the pre-echo Hub value -> the echo arrives (elem.value moves to
        # "hello"). Through the window the field honours the COMMITTED value, so
        # the user keeps seeing what they committed rather than a reverted stale
        # value; once the Hub echoes the commit, the field honours the Hub again
        # and the record clears. Honouring the committed value locally is the
        # load-bearing half of the durability fix — the earlier design reverted
        # to the pre-echo value here, which was the durability bug's root.
        fake = _FakeImgui(
            _Frame(typed="hello", active=True, committed=False),
            _Frame(typed=None, active=False, committed=True),
            _Frame(typed=None, active=False, committed=False),
            _Frame(typed=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _input(value="")  # pre-echo Hub value; the echo has not arrived
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(elem)  # typing (active)
        renderer.render(elem)  # blur -> commit fires once
        renderer.render(elem)  # idle; elem.value is still the pre-echo ""
        renderer.render(_input(value="hello"))  # the Hub echo has landed

        assert [e.value for e in fired] == ["hello"]  # exactly one commit fire
        # Frame 2 shows the buffer (editing carried over); frame 3, now idle,
        # shows the committed value optimistically; frame 4, echo landed, honours
        # the Hub (now equal to the committed value).
        assert fake.recorded == ["", "hello", "hello", "hello"]

    def test_agent_override_mid_window_tracks_the_hub_not_the_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # AGENT-OVERRIDE-MID-WINDOW through the paint seam: commit "v1" while the
        # pre-echo Hub value is "" (the commit-hub marker). An idle frame in the
        # window renders the committed "v1" optimistically; but when the agent
        # drives value= to a DIVERGENT THIRD value ("v2") mid-window, the base
        # handed to imgui must track the Hub ("v2"), not the committed "v1" — the
        # override drops the optimistic echo. This drives the commit-hub marker
        # with a distinct third value, which the "" cases never exercise.
        fake = _FakeImgui(
            _Frame(typed="v1", active=True, committed=False),
            _Frame(typed=None, active=False, committed=True),
            _Frame(typed=None, active=False, committed=False),
            _Frame(typed=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _input(value="")  # pre-echo Hub value observed at commit time
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(elem)  # typing (active)
        renderer.render(elem)  # blur -> commit "v1" fires once; commit-hub is ""
        renderer.render(elem)  # idle; Hub still "" -> optimistic committed "v1"
        renderer.render(_input(value="v2"))  # agent override to a third value

        assert [e.value for e in fired] == ["v1"]  # exactly one commit fire
        # Frame 4's base is the Hub "v2" (the override), NOT the committed "v1":
        # the marker no longer matches, so resolve forgets the commit and honours
        # the Hub.
        assert fake.recorded == ["", "v1", "v1", "v2"]

    def test_edit_in_the_window_wins_over_the_pending_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # EDITING-WINS-OVER-PENDING-COMMIT end to end: commit "v1" (echo in
        # flight), then re-focus and type "fresh" while the commit-echo record is
        # still live. The live buffer is authoritative — the base handed to imgui
        # becomes "fresh", not the pending committed "v1" — and only the first
        # edit's commit fires.
        fake = _FakeImgui(
            _Frame(typed="v1", active=True, committed=False),
            _Frame(typed=None, active=False, committed=True),
            _Frame(typed="fresh", active=True, committed=False),
            _Frame(typed=None, active=True, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _input(value="")  # elem.value stays pre-echo; the record is live
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(elem)  # typing (active)
        renderer.render(elem)  # blur -> commit "v1"; record now live
        renderer.render(elem)  # re-focus, edit "fresh": buffer becomes authoritative
        renderer.render(elem)  # still active: the live buffer wins

        assert [e.value for e in fired] == ["v1"]  # only the first edit committed
        # Frame 3 shows the optimistic committed "v1" (resolve runs before the
        # edit is observed); frame 4 shows the live buffer "fresh" — editing beats
        # the pending commit.
        assert fake.recorded == ["", "v1", "v1", "fresh"]


class TestRendererRefocusDurability:
    def test_refocus_in_the_echo_window_edits_from_the_committed_base(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # REFOCUS-DURABILITY (the reported residual): commit v1 while the echo is
        # in flight (elem.value stays the pre-echo ""), then RE-FOCUS without
        # editing, then type and commit again. The field must show the committed
        # v1 on re-focus and build the second edit on v1 — never on the stale
        # pre-echo "". Both naive designs snapshot the stale base on re-focus and
        # lose v1; this asserts the base handed to imgui on the re-focus and the
        # typing frame is the committed v1.
        frames = (
            _Frame(typed="v1", active=True, committed=False),  # type v1
            _Frame(typed=None, active=False, committed=True),  # commit v1
            _Frame(typed=None, active=False, committed=False),  # idle, echo pending
            _Frame(typed=None, active=True, committed=False),  # re-focus, no edit
            _Frame(typed="v1!", active=True, committed=False),  # type from v1 base
            _Frame(typed=None, active=False, committed=True),  # commit v1!
        )
        fake = _FakeImgui(*frames)
        _install(monkeypatch, fake)
        elem = _input(value="")  # elem.value stays "" — the echo never arrives
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputTextRenderer(WidgetState())

        for _ in frames:
            renderer.render(elem)

        # Both commits carry the durable value: v1, then v1! built on v1 — never
        # a commit of the stale "".
        assert [e.value for e in fired] == ["v1", "v1!"]
        # The re-focus (index 3) and the following keystroke (index 4) were both
        # handed the committed "v1", not the stale pre-echo "".
        assert fake.recorded == ["", "v1", "v1", "v1", "v1", "v1!"]

    def test_defer_on_focus_naive_loses_the_committed_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Fidelity — the old code: with _DeferOnFocusArbiter driving the renderer,
        # the re-focus frame snapshots the raw pre-echo "" as the buffer, and the
        # following keystroke edits from that stale base, not from committed v1.
        # The loss shows in the base handed to imgui (recorded), the value a real
        # user would see and type over — the real arbiter hands "v1" there.
        recorded, _ = _drive_refocus(monkeypatch, _DeferOnFocusArbiter)
        assert recorded[3] == ""  # re-focus snapshots the stale base — the bug
        assert recorded[4] == ""  # the keystroke edits from the stale base

    def test_raw_honour_naive_loses_the_committed_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Fidelity — the tempting incomplete fix: _RawHonourArbiter defers only
        # after a real edit (so it never defers on focus) but honours the raw
        # Hub value, so the re-focus and the following keystroke build on the
        # stale pre-echo "" — the type-before-echo route the model proved loses.
        recorded, _ = _drive_refocus(monkeypatch, _RawHonourArbiter)
        assert recorded[3] == ""  # honours the raw pre-echo value — the bug
        assert recorded[4] == ""  # the keystroke's base is stale


def _drive_refocus(
    monkeypatch: pytest.MonkeyPatch,
    arbiter_cls: type,
) -> tuple[list[str], list[ValueChanged]]:
    """Drive the refocus-durability frame script with ``arbiter_cls`` installed.

    Returns the recorded buffers handed to imgui and the fired events, so a
    fidelity test can assert where a naive arbiter goes stale.
    """
    frames = (
        _Frame(typed="v1", active=True, committed=False),
        _Frame(typed=None, active=False, committed=True),
        _Frame(typed=None, active=False, committed=False),
        _Frame(typed=None, active=True, committed=False),
        _Frame(typed="v1!", active=True, committed=False),
        _Frame(typed=None, active=False, committed=True),
    )
    fake = _FakeImgui(*frames)
    _install(monkeypatch, fake)
    monkeypatch.setattr(input_text_renderer, "InputTextArbiter", arbiter_cls)
    elem = _input(value="")
    fired: list[ValueChanged] = []
    elem.add_handler(ValueChanged, fired.append)
    renderer = InputTextRenderer(WidgetState())
    for _ in frames:
        renderer.render(elem)
    return fake.recorded, fired


class TestRendererFidelity:
    def test_fire_per_keystroke_naive_emits_one_event_per_character(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NO-KEYSTROKE-FIRE fidelity: a naive renderer that fires on every
        # changed frame emits one event per keystroke; the real renderer fires
        # zero while typing and exactly one on the commit (blur) frame.
        frames = (
            _Frame(typed="h", active=True, committed=False),
            _Frame(typed="he", active=True, committed=False),
            _Frame(typed=None, active=False, committed=True),
        )

        naive_fired: list[str] = []
        naive_fake = _FakeImgui(*frames)
        _install(monkeypatch, naive_fake)
        for _ in frames:
            changed, text = naive_fake.input_text_with_hint("l", "", "")
            if changed:
                naive_fired.append(text)
        assert naive_fired == ["h", "he"]  # one fire per keystroke — the bug

        real_fired: list[ValueChanged] = []
        elem = _input(value="")
        elem.add_handler(ValueChanged, real_fired.append)
        _install(monkeypatch, _FakeImgui(*frames))
        renderer = InputTextRenderer(WidgetState())
        for _ in frames:
            renderer.render(elem)
        assert [e.value for e in real_fired] == ["he"]  # one fire on commit


class TestRemovalMidEdit:
    def test_removal_mid_edit_drops_the_buffer_without_committing(self) -> None:
        """A field removed mid-edit drops its in-progress text and does not commit.

        Removal clears the buffer, editing flag, and commit-echo slots via
        ``discard_for``; it never reaches the commit path
        (``is_item_deactivated_after_edit``), so no ``ValueChanged`` fires. This
        is intended — a removed field does not commit, and a re-added same-id
        field honours its fresh Hub value.
        """
        ws = WidgetState()
        arb = InputTextArbiter(ws, "it")
        arb.observe(edited=True, text="draf")  # mid-edit: editing set, buffer held
        assert arb.resolve("hub") == "draf"  # the buffer wins while editing

        elem = _input(value="hub")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)

        ws.discard_for("it")  # the element is removed mid-edit

        assert fired == []  # removal is not a commit — no ValueChanged
        # The in-progress draft is gone; a re-added field honours its fresh value.
        assert InputTextArbiter(ws, "it").resolve("fresh") == "fresh"

    def test_removal_clears_a_pending_commit_echo(self) -> None:
        """Removal drops a pending commit-echo record so a re-added field is clean.

        A commit whose echo has not arrived leaves the committed value recorded;
        removing the element must clear it, so a re-added same-id field honours
        its fresh Hub value rather than a previous field's optimistic echo.
        """
        ws = WidgetState()
        arb = InputTextArbiter(ws, "it")
        arb.commit("stale", hub_value="")
        assert arb.resolve("") == "stale"  # pending: honour the committed value

        ws.discard_for("it")  # the element is removed while the echo is pending

        assert InputTextArbiter(ws, "it").resolve("fresh") == "fresh"
