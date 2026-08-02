"""RgbaBuffer's buffer read — what a malformed or absent color slot resolves to.

The read is the per-frame path, so every rejection falls back to the Hub color
rather than raising: an unreadable slot must not take the display down.
"""

from __future__ import annotations

from punt_lux.scene.rgba_buffer import RgbaBuffer
from punt_lux.scene.widget_state import WidgetState

_HUB = (0.1, 0.2, 0.3, 1.0)


class TestRgbaBufferRead:
    def test_absent_key_returns_the_default(self) -> None:
        assert RgbaBuffer().read(WidgetState(), "missing", _HUB) == _HUB

    def test_stored_four_tuple_reads_back(self) -> None:
        ws = WidgetState()
        ws.set("c", (0.5, 0.6, 0.7, 0.8))
        assert RgbaBuffer().read(ws, "c", _HUB) == (0.5, 0.6, 0.7, 0.8)

    def test_stored_three_tuple_pads_to_arity_four(self) -> None:
        # resolve's editing branch returns the buffer uncoerced, so the read
        # must guarantee arity 4 — a length-3 store pads its alpha to opaque.
        ws = WidgetState()
        ws.set("c", (0.5, 0.6, 0.7))
        assert RgbaBuffer().read(ws, "c", _HUB) == (0.5, 0.6, 0.7, 1.0)

    def test_int_components_coerce_to_float(self) -> None:
        ws = WidgetState()
        ws.set("c", (1, 0, 0, 1))
        assert RgbaBuffer().read(ws, "c", _HUB) == (1.0, 0.0, 0.0, 1.0)

    def test_wrong_arity_reads_as_the_default(self) -> None:
        ws = WidgetState()
        ws.set("c", (0.1, 0.2))
        assert RgbaBuffer().read(ws, "c", _HUB) == _HUB

    def test_non_tuple_reads_as_the_default(self) -> None:
        ws = WidgetState()
        ws.set("c", "#FFFFFF")
        assert RgbaBuffer().read(ws, "c", _HUB) == _HUB

    def test_bool_component_reads_as_the_default(self) -> None:
        # A bool is not a color channel — never coerce True to 1.0.
        ws = WidgetState()
        ws.set("c", (True, 0.0, 0.0, 1.0))
        assert RgbaBuffer().read(ws, "c", _HUB) == _HUB

    def test_non_finite_component_reads_as_the_default(self) -> None:
        # A NaN would break tuple-equality reflexivity; reject the whole tuple.
        ws = WidgetState()
        ws.set("c", (float("nan"), 0.0, 0.0, 1.0))
        assert RgbaBuffer().read(ws, "c", _HUB) == _HUB
