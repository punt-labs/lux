"""InteractionEventBuilder maps element kind + wire value to a typed event.

Each per-kind arm validates the value's shape at the boundary (PY-EH-1): a
checkbox toggle must carry ``bool``, an input_text edit ``str``, a button a
``True``. A wrong-shaped value or an unrecognised kind raises
``WrongKindError`` naming what was expected.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.interaction_errors import WrongKindError
from punt_lux.domain.interaction_event_builder import InteractionEventBuilder
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.text import TextElement

_SCENE = SceneId("s")
_ELEM = ElementId("e")
_OWNER = ClientId("c")


def _build(element: object, value: object) -> object:
    return InteractionEventBuilder().build(
        element=element,  # type: ignore[arg-type]  # only .kind is read
        scene_id=_SCENE,
        element_id=_ELEM,
        owner_id=_OWNER,
        value=value,
    )


class TestCheckboxArm:
    def test_bool_value_builds_value_changed(self) -> None:
        event = _build(CheckboxElement(id="c"), True)
        assert isinstance(event, ValueChanged)
        assert event.value is True

    def test_non_bool_value_is_rejected(self) -> None:
        with pytest.raises(WrongKindError) as exc:
            _build(CheckboxElement(id="c"), "on")
        assert exc.value.expected == "checkbox value (bool)"

    def test_int_is_not_accepted_as_a_bool(self) -> None:
        with pytest.raises(WrongKindError):
            _build(CheckboxElement(id="c"), 1)


class TestInputTextArm:
    def test_str_value_builds_value_changed(self) -> None:
        event = _build(InputTextElement(id="i"), "Ada")
        assert isinstance(event, ValueChanged)
        assert event.value == "Ada"

    def test_bool_value_is_rejected(self) -> None:
        with pytest.raises(WrongKindError) as exc:
            _build(InputTextElement(id="i"), True)
        assert exc.value.expected == "input_text value (str)"

    def test_non_str_value_is_rejected(self) -> None:
        with pytest.raises(WrongKindError) as exc:
            _build(InputTextElement(id="i"), 7)
        assert exc.value.expected == "input_text value (str)"


class TestButtonArm:
    def test_true_builds_button_clicked(self) -> None:
        event = _build(ButtonElement(id="b", label="Go"), True)
        assert isinstance(event, ButtonClicked)

    def test_non_true_is_rejected(self) -> None:
        with pytest.raises(WrongKindError):
            _build(ButtonElement(id="b", label="Go"), False)


class TestUnknownKind:
    def test_unrecognised_kind_is_rejected(self) -> None:
        with pytest.raises(WrongKindError) as exc:
            _build(TextElement(id="t", content="hi"), True)
        assert "input_text" in exc.value.expected
