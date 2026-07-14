"""CheckboxRenderer honours the Hub-authoritative value and fires on toggle.

The ``imgui.checkbox`` call is a visual-only seam that segfaults without a live
GL context, so these tests drive ``render`` through a fake imgui that records the
value handed to ``checkbox`` and returns a scripted ``(changed, value)`` result.
Invariants of a Hub-authoritative ABC checkbox are covered:

- HONOUR — every frame renders the current ``elem.value``, never a stale seed.
- USER TOGGLE FIRES ONCE — a genuine click fires exactly one ``ValueChanged``
  carrying the new value, both when checking (False->True) and unchecking.
- NO ECHO — a Hub re-push (``changed`` False) never fires.
- STATELESS — one renderer instance paints many ids, each honouring its own
  value with no cross-contamination.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers import checkbox_renderer
from punt_lux.display.renderers.checkbox_renderer import CheckboxRenderer
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.checkbox import CheckboxElement

if TYPE_CHECKING:
    import pytest


class _FakeImgui:
    """Fake imgui recording each ``current`` value and returning a fixed result.

    Substitutes for the real ``imgui`` module inside ``checkbox_renderer`` so a
    render is driven without a GL context. ``recorded`` is the sequence of
    values ``render`` passed to ``checkbox`` — the honour evidence.
    """

    recorded: list[bool]
    _result: tuple[bool, bool]

    def __new__(cls, *, changed: bool, value: bool) -> Self:
        self = super().__new__(cls)
        self.recorded = []
        self._result = (changed, value)
        return self

    def checkbox(self, _label: str, current: bool) -> tuple[bool, bool]:
        self.recorded.append(current)
        return self._result


def _checkbox(*, value: bool) -> CheckboxElement:
    return CheckboxElement(id="cbx", label="On", value=value)


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeImgui) -> None:
    monkeypatch.setattr(checkbox_renderer, "imgui", fake)


def test_render_honours_the_hub_value_each_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A Hub re-push swaps in a new element with the updated value; the renderer
    # must paint that value, not a value cached from an earlier frame. The old
    # widget_state seeding returned the stale first-frame value here.
    fake = _FakeImgui(changed=False, value=False)
    _install(monkeypatch, fake)
    renderer = CheckboxRenderer()

    renderer.render(_checkbox(value=False))
    renderer.render(_checkbox(value=True))

    assert fake.recorded == [False, True]


def test_user_toggle_fires_one_value_changed_with_the_new_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeImgui(changed=True, value=True)
    _install(monkeypatch, fake)
    elem = _checkbox(value=False)
    fired: list[ValueChanged] = []
    elem.add_handler(ValueChanged, fired.append)

    CheckboxRenderer().render(elem)

    assert len(fired) == 1
    assert fired[0].value is True
    assert fired[0].element_id == "cbx"


def test_user_untoggle_fires_one_value_changed_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Uncheck: the mirror of the toggle-ON case. A genuine click on a checked
    # box fires exactly one ValueChanged carrying the new False value — the
    # toggle-ON test alone left the False direction unproven.
    fake = _FakeImgui(changed=True, value=False)
    _install(monkeypatch, fake)
    elem = _checkbox(value=True)
    fired: list[ValueChanged] = []
    elem.add_handler(ValueChanged, fired.append)

    CheckboxRenderer().render(elem)

    assert len(fired) == 1
    assert fired[0].value is False
    assert fired[0].element_id == "cbx"


def test_one_renderer_honours_each_id_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The renderer holds no per-scene or per-id state: one instance paints two
    # DIFFERENT elements and each reports its own elem.value, with nothing from
    # the first bleeding into the second.
    fake = _FakeImgui(changed=False, value=False)
    _install(monkeypatch, fake)
    renderer = CheckboxRenderer()

    renderer.render(CheckboxElement(id="a", label="A", value=True))
    renderer.render(CheckboxElement(id="b", label="B", value=False))

    assert fake.recorded == [True, False]


def test_hub_repush_does_not_echo_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``changed`` False models a frame where the Hub value was painted but no
    # user clicked — the re-push echo must not fire ValueChanged.
    fake = _FakeImgui(changed=False, value=True)
    _install(monkeypatch, fake)
    elem = _checkbox(value=True)
    fired: list[ValueChanged] = []
    elem.add_handler(ValueChanged, fired.append)

    CheckboxRenderer().render(elem)

    assert fired == []
