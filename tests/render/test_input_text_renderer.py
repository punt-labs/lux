"""InputTextRenderer + InputTextArbiter honour the Hub value without clobbering.

The ``imgui.input_text`` call needs a live GL context, so the renderer tests
drive ``render`` through a fake imgui that records the buffer handed to
``input_text`` and returns a scripted ``(changed, value)``. The buffer/honour
decision itself is the pure ``InputTextArbiter``, tested without imgui.

Four invariants of a Hub-authoritative text input, each fidelity-checked against
the two naive implementations it must beat — "render ``elem.value`` every frame"
and "seed the buffer once via ``ensure``":

- HONOUR — an agent-driven ``value`` change reaches the rendered buffer next
  frame (a seed-once buffer would keep painting the stale first value).
- NO-CLOBBER — while ``value`` equals the honoured value (the user is typing, no
  Hub drive) the in-progress buffer survives (render-every-frame would reset it).
- FIRE-ON-EDIT — a user edit fires exactly one ``ValueChanged`` with the text.
- ECHO-SUPPRESSION — the Hub re-pushing the just-typed text neither re-fires nor
  clobbers the buffer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers import input_text_renderer
from punt_lux.display.renderers.imgui.input_text_selection import (
    _UNHONOURED,
    InputTextArbiter,
)
from punt_lux.display.renderers.input_text_renderer import InputTextRenderer
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest


class _FakeImgui:
    """Fake imgui recording each buffer passed and returning a scripted result.

    ``recorded`` is the sequence of buffers ``render`` handed to ``input_text``
    — the honour evidence.
    """

    recorded: list[str]
    _result: tuple[bool, str]

    def __new__(cls, *, changed: bool, value: str) -> Self:
        self = super().__new__(cls)
        self.recorded = []
        self._result = (changed, value)
        return self

    def input_text(self, _label: str, current: str) -> tuple[bool, str]:
        self.recorded.append(current)
        return self._result

    def input_text_with_hint(
        self, _label: str, _hint: str, current: str
    ) -> tuple[bool, str]:
        self.recorded.append(current)
        return self._result


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(input_text_renderer, "imgui", fake)


def _input(*, value: str = "", hint: str = "") -> InputTextElement:
    return InputTextElement(id="it", label="Name", value=value, hint=hint)


# -- the arbiter: the pure buffer/honour decision --------------------------


class TestArbiterHonour:
    def test_first_frame_honours_the_hub_value(self) -> None:
        arb = InputTextArbiter(WidgetState(), "it")
        assert arb.buffer("abc") == "abc"

    def test_hub_drive_replaces_the_buffer_next_frame(self) -> None:
        # HONOUR: an agent-set value differing from the honoured value is a Hub
        # drive; the arbiter syncs the buffer to it.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.buffer("abc")
        assert arb.buffer("xyz") == "xyz"

    def test_no_drive_keeps_the_in_progress_buffer(self) -> None:
        # NO-CLOBBER: while value == honoured (no Hub drive) a user edit stored
        # in the buffer survives — the Hub's own lagging echo does not reset it.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.buffer("abc")
        arb.record_edit("abcd")
        assert arb.buffer("abc") == "abcd"
        assert arb.buffer("abc") == "abcd"

    def test_echo_of_typed_text_is_consumed_without_clobber(self) -> None:
        # ECHO-SUPPRESSION: the user types "abc"; the Hub echoes value="abc".
        # The echo advances the honoured slot once, with the buffer already
        # equal to it, so nothing is reset.
        arb = InputTextArbiter(WidgetState(), "it")
        arb.buffer("")  # honour the empty initial value
        arb.record_edit("abc")
        assert arb.buffer("abc") == "abc"
        assert arb.buffer("abc") == "abc"

    def test_slots_are_id_scoped(self) -> None:
        ws = WidgetState()
        InputTextArbiter(ws, "a").buffer("aaa")
        InputTextArbiter(ws, "b").buffer("bbb")
        assert InputTextArbiter(ws, "a").buffer("aaa") == "aaa"
        assert InputTextArbiter(ws, "b").buffer("bbb") == "bbb"


# -- fidelity: the two naive implementations each invariant must beat -------


class _RenderEveryFrameArbiter:
    """Naive: always paint ``value``; a user edit is not remembered."""

    def buffer(self, value: str) -> str:
        return value

    def record_edit(self, _text: str) -> None:
        return None


class _SeedOnceArbiter:
    """Naive: seed the buffer once via ``ensure``; later Hub drives are lost."""

    _state: WidgetState
    _key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._key = element_id
        return self

    def buffer(self, value: str) -> str:
        return str(self._state.ensure(self._key, value))

    def record_edit(self, text: str) -> None:
        self._state.set(self._key, text)


class TestFidelity:
    def test_render_every_frame_violates_no_clobber(self) -> None:
        # The render-every-frame naive resets the in-progress buffer to the
        # stale Hub value; the real arbiter keeps the typed text.
        naive = _RenderEveryFrameArbiter()
        naive.buffer("abc")
        naive.record_edit("abcd")
        assert naive.buffer("abc") == "abc"  # clobbered — the bug

        real = InputTextArbiter(WidgetState(), "it")
        real.buffer("abc")
        real.record_edit("abcd")
        assert real.buffer("abc") == "abcd"  # survives — the fix

    def test_seed_once_violates_honour(self) -> None:
        # The seed-once naive ignores a later Hub drive; the real arbiter honours
        # it.
        naive = _SeedOnceArbiter(WidgetState(), "it")
        naive.buffer("abc")
        assert naive.buffer("xyz") == "abc"  # stale — the bug

        real = InputTextArbiter(WidgetState(), "it")
        real.buffer("abc")
        assert real.buffer("xyz") == "xyz"  # honoured — the fix

    def test_unhonoured_sentinel_is_distinct_from_any_text(self) -> None:
        # The honoured slot starts at a sentinel no real string equals, so the
        # very first frame is always treated as a Hub drive and honoured.
        ws = WidgetState()
        assert ws.get("it:input_honoured", _UNHONOURED) is _UNHONOURED
        assert InputTextArbiter(ws, "it").buffer("") == ""


# -- the renderer: fire on edit, no echo fire, honour through the paint ----


class TestRendererFire:
    def test_user_edit_fires_one_value_changed_with_the_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _FakeImgui(changed=True, value="typed"))
        elem = _input(value="")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)

        InputTextRenderer(WidgetState()).render(elem)

        assert len(fired) == 1
        assert fired[0].value == "typed"
        assert fired[0].element_id == "it"

    def test_no_user_edit_does_not_fire(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A Hub re-push frame (changed False) paints the value but must not fire.
        _install(monkeypatch, _FakeImgui(changed=False, value="abc"))
        elem = _input(value="abc")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)

        InputTextRenderer(WidgetState()).render(elem)

        assert fired == []

    def test_hint_variant_paints_and_fires(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeImgui(changed=True, value="typed")
        _install(monkeypatch, fake)
        elem = _input(value="", hint="type a name")
        fired: list[ValueChanged] = []
        elem.add_handler(ValueChanged, fired.append)

        InputTextRenderer(WidgetState()).render(elem)

        assert fake.recorded == [""]
        assert len(fired) == 1

    def test_render_honours_hub_value_across_frames(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # HONOUR through the real paint seam: a re-push swaps in a new element
        # with a new value; the buffer handed to imgui tracks it, not a stale
        # seed.
        fake = _FakeImgui(changed=False, value="")
        _install(monkeypatch, fake)
        renderer = InputTextRenderer(WidgetState())

        renderer.render(_input(value="abc"))
        renderer.render(_input(value="xyz"))

        assert fake.recorded == ["abc", "xyz"]
