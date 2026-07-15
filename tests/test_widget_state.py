"""WidgetState numeric accessor and the slider commit-echo slot clearing.

The slider path reads its buffer through ``get_float`` (a numeric miss falls
back to the caller's default, never a magic ``""``) and stores its
editing/commit-echo state under the ``SLIDER_*`` suffixes, which ``discard_for``
clears on removal so a re-added same-id slider starts clean.
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


class TestSliderSlotClearing:
    def test_discard_for_clears_every_slider_slot(self) -> None:
        ws = WidgetState()
        eid = "vol"
        ws.set(f"{eid}{WidgetState.SLIDER_EDITING_SUFFIX}", value=True)
        ws.set(f"{eid}{WidgetState.SLIDER_COMMITTED_SUFFIX}", 80.0)
        ws.set(f"{eid}{WidgetState.SLIDER_COMMIT_HUB_SUFFIX}", 50.0)

        ws.discard_for(eid)

        assert ws.get(f"{eid}{WidgetState.SLIDER_EDITING_SUFFIX}") is None
        assert ws.get(f"{eid}{WidgetState.SLIDER_COMMITTED_SUFFIX}") is None
        assert ws.get(f"{eid}{WidgetState.SLIDER_COMMIT_HUB_SUFFIX}") is None

    def test_slider_suffixes_are_distinct_from_input_suffixes(self) -> None:
        # The fork keeps the two triples independent — a rename to one neutral
        # set is the color_picker extraction's job, not this migration's.
        input_suffixes = {
            WidgetState.INPUT_EDITING_SUFFIX,
            WidgetState.INPUT_COMMITTED_SUFFIX,
            WidgetState.INPUT_COMMIT_HUB_SUFFIX,
        }
        slider_suffixes = {
            WidgetState.SLIDER_EDITING_SUFFIX,
            WidgetState.SLIDER_COMMITTED_SUFFIX,
            WidgetState.SLIDER_COMMIT_HUB_SUFFIX,
        }
        assert input_suffixes.isdisjoint(slider_suffixes)
