"""The three ValueAccessor leaves — read hit/miss policy and committed coerce.

Each accessor carries exactly the two carrier-typed touches the shared
ContinuousEditArbiter delegates: a buffer ``read`` (with its per-type miss
policy) and a committed ``coerce``. The miss policy is the load-bearing
asymmetry — ``input_text`` reads ``""`` on a miss (a cleared field is real
state), while ``slider``/``color_picker`` fall back to the current Hub value.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.continuous_edit_accessors import (
    ColorValueAccessor,
    FloatValueAccessor,
    StrValueAccessor,
)
from punt_lux.display.renderers.imgui.continuous_edit_selection import ValueAccessor
from punt_lux.scene.widget_state import WidgetState

_HUB: tuple[float, float, float, float] = (0.1, 0.2, 0.3, 1.0)


class TestValueAccessorProtocol:
    def test_every_accessor_satisfies_the_protocol_structurally(self) -> None:
        # PY-TS-6: the family contract is a runtime_checkable Protocol, not a base.
        assert isinstance(StrValueAccessor(), ValueAccessor)
        assert isinstance(FloatValueAccessor(), ValueAccessor)
        assert isinstance(ColorValueAccessor(), ValueAccessor)


class TestStrValueAccessor:
    def test_read_returns_the_stored_buffer(self) -> None:
        ws = WidgetState()
        ws.set("k", "typed")
        assert StrValueAccessor().read(ws, "k", hub_value="hub") == "typed"

    def test_read_miss_returns_empty_ignoring_hub_value(self) -> None:
        # A cleared field is a real state: the miss must NOT fall back to the Hub.
        assert StrValueAccessor().read(WidgetState(), "k", hub_value="hub") == ""

    def test_coerce_casts_to_str(self) -> None:
        assert StrValueAccessor().coerce("done") == "done"
        assert StrValueAccessor().coerce(42) == "42"


class TestFloatValueAccessor:
    def test_read_returns_the_stored_buffer(self) -> None:
        ws = WidgetState()
        ws.set("k", 30)
        result = FloatValueAccessor().read(ws, "k", hub_value=99.0)
        assert result == 30.0
        assert isinstance(result, float)

    def test_read_miss_falls_back_to_hub_value(self) -> None:
        # Every float is a value, so a miss defaults to the current Hub value.
        assert FloatValueAccessor().read(WidgetState(), "k", hub_value=99.0) == 99.0

    def test_coerce_casts_to_float(self) -> None:
        assert FloatValueAccessor().coerce(7) == 7.0
        assert isinstance(FloatValueAccessor().coerce(7), float)


class TestColorValueAccessor:
    def test_read_returns_the_stored_buffer_normalized_to_arity_four(self) -> None:
        ws = WidgetState()
        ws.set("k", (0.5, 0.6, 0.7))
        result = ColorValueAccessor().read(ws, "k", hub_value=_HUB)
        assert result == (0.5, 0.6, 0.7, 1.0)

    def test_read_miss_falls_back_to_hub_value(self) -> None:
        assert ColorValueAccessor().read(WidgetState(), "k", hub_value=_HUB) == _HUB

    def test_coerce_parses_a_stored_tuple(self) -> None:
        assert ColorValueAccessor().coerce((1.0, 0.0, 0.0, 1.0)) == (1.0, 0.0, 0.0, 1.0)
