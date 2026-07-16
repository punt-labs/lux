"""RadioRenderer honours the Hub selection and labels an empty group.

The ``imgui.radio_button`` call is a visual-only seam that segfaults without a
live GL context, so these tests drive ``render`` through a fake imgui that
records every ``text`` label and each ``radio_button`` active-state, returning a
scripted click per button. Invariants of a Hub-authoritative ABC radio:

- LABEL — a populated group paints its label before the buttons.
- EMPTY-GROUP PARITY — an empty-but-valid group (awaiting deferred population,
  accepted by ``validate()``) paints ``f"{label}: (empty)"`` and draws no
  buttons, matching ``ComboRenderer`` rather than rendering nothing.
- HONOUR — each button is active iff its index equals ``elem.selected``.
- USER PICK FIRES ONCE — a click on a different item fires exactly one
  ``ValueChanged`` carrying the new index; re-picking the current item does not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers import radio_renderer
from punt_lux.display.renderers.radio_renderer import RadioRenderer
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.radio import RadioElement

if TYPE_CHECKING:
    import pytest


class _FakeImgui:
    """Fake imgui recording ``text`` labels and ``radio_button`` active flags.

    Substitutes for the real ``imgui`` module inside ``radio_renderer`` so a
    render runs without a GL context. ``texts`` captures every ``text`` label;
    ``actives`` captures each button's active flag — the honour evidence. A
    button whose index is in ``_click_indices`` reports a press.
    """

    texts: list[str]
    actives: list[bool]
    _click_indices: frozenset[int]
    _button_index: int

    def __new__(cls, *click_indices: int) -> Self:
        self = super().__new__(cls)
        self.texts = []
        self.actives = []
        self._click_indices = frozenset(click_indices)
        self._button_index = 0
        return self

    def text(self, label: str) -> None:
        self.texts.append(label)

    def radio_button(self, _label: str, active: bool) -> bool:
        self.actives.append(active)
        pressed = self._button_index in self._click_indices
        self._button_index += 1
        return pressed

    def same_line(self) -> None:
        return None


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(radio_renderer, "imgui", fake)


def test_empty_group_paints_its_label(monkeypatch: pytest.MonkeyPatch) -> None:
    # EMPTY-GROUP PARITY: an empty-but-valid radio (items awaiting deferred
    # population) must show its label — matching ComboRenderer's "(empty)" — not
    # render nothing. The prior early return drew no widget at all.
    fake = _FakeImgui()
    _install(monkeypatch, fake)

    RadioRenderer().render(RadioElement(id="ra", label="Pick", items=[], selected=0))

    assert fake.texts == ["Pick: (empty)"]
    assert fake.actives == []


def test_populated_group_paints_its_label_then_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LABEL + HONOUR: the label is drawn first, then one button per item, each
    # active iff its index equals elem.selected.
    fake = _FakeImgui()
    _install(monkeypatch, fake)

    RadioRenderer().render(
        RadioElement(id="ra", label="Pick", items=["A", "B", "C"], selected=1)
    )

    assert fake.texts == ["Pick"]
    assert fake.actives == [False, True, False]


def test_user_pick_fires_one_value_changed_with_the_new_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeImgui(2)  # the user clicks the third button
    _install(monkeypatch, fake)
    elem = RadioElement(id="ra", label="Pick", items=["A", "B", "C"], selected=0)
    fired: list[ValueChanged] = []
    elem.add_handler(ValueChanged, fired.append)

    RadioRenderer().render(elem)

    assert len(fired) == 1
    assert fired[0].value == 2
    assert fired[0].element_id == "ra"


def test_reclick_current_item_does_not_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A press on the already-selected item reports a click but the index is
    # unchanged, so no ValueChanged fires — only a genuine move does.
    fake = _FakeImgui(1)  # the user clicks the already-selected button
    _install(monkeypatch, fake)
    elem = RadioElement(id="ra", label="Pick", items=["A", "B", "C"], selected=1)
    fired: list[ValueChanged] = []
    elem.add_handler(ValueChanged, fired.append)

    RadioRenderer().render(elem)

    assert fired == []
