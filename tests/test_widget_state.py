"""WidgetState's numeric accessor and the commit-echo slot clearing.

The slider path reads its buffer through ``get_float``: a numeric miss falls
back to the caller's default, never a magic ``""``. Every non-atomic mutable
kind stores its buffer and
commit-echo state under the one shared ``CONTINUOUS_EDIT_*`` quad, which
``discard_for`` clears on removal so a re-added same-id widget starts clean.
"""

from __future__ import annotations

from punt_lux.scene.widget_state import WidgetState


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
