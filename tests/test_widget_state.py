"""WidgetState numeric/tuple accessors and the commit-echo slot clearing.

The slider path reads its buffer through ``get_float`` (a numeric miss falls
back to the caller's default, never a magic ``""``) and the color_picker path
through ``get_tuple`` (an RGBA-tuple miss falls back the same way, always
normalized to arity 4). Every non-atomic mutable kind stores its buffer and
commit-echo state under the one shared ``CONTINUOUS_EDIT_*`` quad, which
``discard_for`` clears on removal so a re-added same-id widget starts clean.
"""

from __future__ import annotations

from punt_lux.scene.widget_state import WidgetState

_HUB = (0.1, 0.2, 0.3, 1.0)


class TestGetFloat:
    def test_absent_key_returns_the_default(self) -> None:
        assert WidgetState().get_float("missing", default=1.5) == 1.5

    def test_stored_number_reads_back_as_float(self) -> None:
        ws = WidgetState()
        ws.set("s", 42)
        assert ws.get_float("s", default=0.0) == 42.0
        assert isinstance(ws.get_float("s", default=0.0), float)

    def test_stored_bool_reads_as_the_default(self) -> None:
        # A bool is not a slider value — never coerce True to 1.0.
        ws = WidgetState()
        ws.set("s", True)
        assert ws.get_float("s", default=7.0) == 7.0

    def test_stored_string_reads_as_the_default(self) -> None:
        ws = WidgetState()
        ws.set("s", "not a number")
        assert ws.get_float("s", default=3.0) == 3.0


class TestGetTuple:
    def test_absent_key_returns_the_default(self) -> None:
        assert WidgetState().get_tuple("missing", default=_HUB) == _HUB

    def test_stored_four_tuple_reads_back(self) -> None:
        ws = WidgetState()
        ws.set("c", (0.5, 0.6, 0.7, 0.8))
        assert ws.get_tuple("c", default=_HUB) == (0.5, 0.6, 0.7, 0.8)

    def test_stored_three_tuple_pads_to_arity_four(self) -> None:
        # resolve's editing branch returns the buffer uncoerced, so get_tuple
        # must guarantee arity 4 — a length-3 store pads its alpha to opaque.
        ws = WidgetState()
        ws.set("c", (0.5, 0.6, 0.7))
        assert ws.get_tuple("c", default=_HUB) == (0.5, 0.6, 0.7, 1.0)

    def test_int_components_coerce_to_float(self) -> None:
        ws = WidgetState()
        ws.set("c", (1, 0, 0, 1))
        assert ws.get_tuple("c", default=_HUB) == (1.0, 0.0, 0.0, 1.0)

    def test_wrong_arity_reads_as_the_default(self) -> None:
        ws = WidgetState()
        ws.set("c", (0.1, 0.2))
        assert ws.get_tuple("c", default=_HUB) == _HUB

    def test_non_tuple_reads_as_the_default(self) -> None:
        ws = WidgetState()
        ws.set("c", "#FFFFFF")
        assert ws.get_tuple("c", default=_HUB) == _HUB

    def test_bool_component_reads_as_the_default(self) -> None:
        # A bool is not a color channel — never coerce True to 1.0.
        ws = WidgetState()
        ws.set("c", (True, 0.0, 0.0, 1.0))
        assert ws.get_tuple("c", default=_HUB) == _HUB

    def test_non_finite_component_reads_as_the_default(self) -> None:
        # A NaN would break tuple-equality reflexivity; reject the whole tuple.
        ws = WidgetState()
        ws.set("c", (float("nan"), 0.0, 0.0, 1.0))
        assert ws.get_tuple("c", default=_HUB) == _HUB


class TestContinuousEditSlotClearing:
    def test_discard_for_clears_every_continuous_edit_slot(self) -> None:
        # One neutral quad serves input_text, slider, and color_picker alike;
        # discard_for clears all four so a re-added same-id widget starts clean.
        ws = WidgetState()
        eid = "bg"
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}", (0.1, 0.2, 0.3))
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_EDITING_SUFFIX}", value=True)
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}", 80.0)
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}", 50.0)

        ws.discard_for(eid)

        assert ws.get(f"{eid}{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}") is None
        assert ws.get(f"{eid}{WidgetState.CONTINUOUS_EDIT_EDITING_SUFFIX}") is None
        assert ws.get(f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}") is None
        assert ws.get(f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}") is None

    def test_continuous_edit_buffer_suffix_does_not_alias_the_bare_id(self) -> None:
        # The buffer takes its own suffix (never the bare id) so it can never
        # collide with a per-patch hex-string mirror of widget_value on one key.
        assert WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX != ""
        assert WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX.startswith(":")
