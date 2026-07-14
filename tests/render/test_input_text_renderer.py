"""InputTextRenderer + InputTextArbiter under the commit-on-idle rule.

The ``imgui.input_text`` call needs a live GL context, so the renderer tests
drive ``render`` through a fake imgui that records the buffer handed to the
widget and returns a scripted per-frame ``(changed, text)`` plus the
``is_item_active`` / ``is_item_deactivated_after_edit`` item-state flags. The
honour-or-defer decision itself is the pure ``InputTextArbiter``, tested without
imgui.

Four invariants of a controlled text input over Hub latency, each
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
        # NO-CLOBBER: once a frame has kept the live text, a Hub-driven value is
        # ignored — the in-progress buffer wins.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.keep("hel")
        assert arb.resolve("ZZZ") == "hel"
        assert arb.resolve("ZZZ") == "hel"

    def test_editing_keeps_a_cleared_field_empty(self) -> None:
        # A user who clears the field is editing an empty buffer — distinct from
        # an idle field, which would fall back to the Hub value.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.keep("")
        assert arb.resolve("hub") == ""

    def test_release_returns_to_honouring_the_hub(self) -> None:
        arb = InputTextArbiter(WidgetState(), "it")
        arb.keep("draft")
        arb.release()
        assert arb.resolve("hub") == "hub"

    def test_slots_are_id_scoped(self) -> None:
        ws = WidgetState()
        InputTextArbiter(ws, "a").keep("aaa")
        assert InputTextArbiter(ws, "a").resolve("x") == "aaa"
        assert InputTextArbiter(ws, "b").resolve("y") == "y"


# -- fidelity: the naive implementations each invariant must beat ----------


class _HonourEveryFrameArbiter:
    """Naive: render the Hub value every frame, ignoring that the user edits."""

    def resolve(self, hub_value: str) -> str:
        return hub_value

    def keep(self, _text: str) -> None:
        return None

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


class TestArbiterFidelity:
    def test_honour_every_frame_clobbers_live_typing(self) -> None:
        # NO-CLOBBER fidelity: the honour-every-frame naive lets a stale Hub
        # value overwrite the buffer mid-edit; the real arbiter defers.
        naive = _HonourEveryFrameArbiter()
        naive.keep("hel")
        assert naive.resolve("stale") == "stale"  # clobbered — the bug

        real = InputTextArbiter(WidgetState(), "it")
        real.keep("hel")
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
    def test_idle_after_commit_renders_the_hub_value_until_the_echo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # POST-COMMIT LATENCY: type (active) -> blur/commit (deactivate-after-edit,
        # one fire) -> a following idle frame while elem.value still holds the
        # pre-commit (stale) Hub value. The commit releases the buffer, so the idle
        # frame honours the Hub again and renders elem.value ("") — the committed
        # text becomes visible only once the Hub echoes it back, the same
        # fire-then-echo latency every interactive element carries. This is the
        # accepted Hub-authoritative behaviour, not a lost edit; the arbiter holds
        # no optimistic-echo state.
        fake = _FakeImgui(
            _Frame(typed="hello", active=True, committed=False),
            _Frame(typed=None, active=False, committed=True),
            _Frame(typed=None, active=False, committed=False),
        )
        _install(monkeypatch, fake)
        elem = _input(value="")  # pre-commit Hub value; the echo has not arrived
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(elem)  # typing (active)
        renderer.render(elem)  # blur -> commit fires once
        renderer.render(elem)  # idle; elem.value is still the stale ""

        assert [e.value for e in fired] == ["hello"]  # exactly one commit fire
        # Frame 2 still shows the buffer (editing carried over); frame 3, now idle,
        # renders the pre-echo Hub value.
        assert fake.recorded == ["", "hello", ""]


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

        Removal clears the buffer and editing flag via ``discard_for``; it never
        reaches the commit path (``is_item_deactivated_after_edit``), so no
        ``ValueChanged`` fires. This is intended — a removed field does not
        commit, and a re-added same-id field honours its fresh Hub value.
        """
        ws = WidgetState()
        arb = InputTextArbiter(ws, "it")
        arb.keep("draf")  # mid-edit: editing flag set, buffer holds the draft
        assert arb.resolve("hub") == "draf"  # the buffer wins while editing

        elem = _input(value="hub")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)

        ws.discard_for("it")  # the element is removed mid-edit

        assert fired == []  # removal is not a commit — no ValueChanged
        # The in-progress draft is gone; a re-added field honours its fresh value.
        assert InputTextArbiter(ws, "it").resolve("fresh") == "fresh"
