"""A patch that leaves a kind invalid is refused before any observer hears of it.

A slider, radio, combo or input number holds invariants that span fields (a value
within its bounds, a selected index within its items). They are judged on the final
state, after every setter and before the observers are told, so an observer never
sees a value the element then takes back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.slider import SliderElement

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.element_abc import Element

_KINDS: list[tuple[Callable[[], Element], dict[str, object], str]] = [
    (lambda: SliderElement(id="e", value=1.0), {"value": 999.0}, "_set_value"),
    (lambda: RadioElement(id="e", items=["a", "b"]), {"selected": 9}, "_set_selected"),
    (lambda: ComboElement(id="e", items=["a", "b"]), {"selected": 9}, "_set_selected"),
    (
        lambda: InputNumberElement(id="e", value=1.0, min=0.0, max=10.0),
        {"value": 99.0},
        "_set_value",
    ),
]
_IDS = ["slider", "radio", "combo", "input_number"]


@pytest.mark.parametrize(("make", "bad", "setter"), _KINDS, ids=_IDS)
def test_an_invalid_final_state_is_refused_before_an_observer_hears_it(
    monkeypatch: pytest.MonkeyPatch,
    make: Callable[[], Element],
    bad: dict[str, object],
    setter: str,
) -> None:
    element = make()
    kind = type(element)
    real = getattr(kind, setter)
    prop = setter.removeprefix("_set_")

    def notifying(this: Element, value: object) -> None:
        real(this, value)
        this._notify_observers(prop)

    monkeypatch.setattr(kind, setter, notifying)
    heard: list[str] = []
    element.add_observer(heard.append)
    before = dict(vars(element))

    with pytest.raises(ValueError):
        element.apply_patch(bad)

    assert heard == []
    assert {k: v for k, v in vars(element).items() if k != "_observers"} == {
        k: v for k, v in before.items() if k != "_observers"
    }
