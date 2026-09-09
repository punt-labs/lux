"""WidgetState's typed accessors and the commit-echo slot clearing.

The store holds ``Any``, so every typed accessor rejects rather than coerces:
the slider path reads its buffer through ``get_float`` and falls back to the
caller's default on a miss, never a magic ``""``, and an arbiter reads its flag
through ``get_bool`` so a slot holding something other than a ``bool`` cannot
decide a widget's state. Every non-atomic mutable kind stores its buffer and
commit-echo state under the one shared ``CONTINUOUS_EDIT_*`` quad, which
``discard_for`` clears on removal so a re-added same-id widget starts clean.
"""

from __future__ import annotations

from punt_lux.display.replica.widget_state import WidgetState


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


class TestGetBool:
    def test_absent_key_returns_the_default(self) -> None:
        assert WidgetState().get_bool("missing", default=True) is True
        assert WidgetState().get_bool("missing", default=False) is False

    def test_stored_flag_reads_back(self) -> None:
        ws = WidgetState()
        ws.set("f", value=True)
        assert ws.get_bool("f", default=False) is True

    def test_stored_string_reads_as_the_default(self) -> None:
        # The store is untyped, so a truthy non-bool must not decide a flag:
        # coercing here is how a header holds itself open on a foreign value.
        ws = WidgetState()
        ws.set("f", "yes")
        assert ws.get_bool("f", default=False) is False

    def test_stored_number_reads_as_the_default(self) -> None:
        ws = WidgetState()
        ws.set("f", 1)
        assert ws.get_bool("f", default=False) is False


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


class TestObservableSnapshot:
    def test_a_bare_element_value_is_included(self) -> None:
        ws = WidgetState()
        ws.set("checkbox1", value=True)
        assert ws.observable_snapshot() == {"checkbox1": True}

    def test_every_gesture_window_slot_is_excluded(self) -> None:
        ws = WidgetState()
        eid = "dlg"
        ws.set(f"{eid}{WidgetState.OPEN_SUFFIX}", value=True)
        ws.set(f"{eid}{WidgetState.DISMISS_SUFFIX}", value=False)
        ws.set(f"{eid}{WidgetState.PENDING_SUFFIX}", "tab2")
        ws.set(f"{eid}{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", value=True)
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}", 0.5)
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_EDITING_SUFFIX}", value=True)
        ws.set(f"{eid}{WidgetState.ROW_SELECTION_PENDING_SUFFIX}", "r1")
        ws.set(f"{eid}{WidgetState.FOCUS_REFOCUS_SUFFIX}", value=True)

        assert ws.observable_snapshot() == {}

    def test_durable_facts_beside_gesture_slots_are_included(self) -> None:
        # Honoured/commit-echo/focus/split-ratio slots are steady-state facts,
        # not mid-click gesture state, so they survive the filter.
        ws = WidgetState()
        eid = "tabs"
        ws.set(f"{eid}{WidgetState.HONOURED_SUFFIX}", "tab1")
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}", 42.0)
        ws.set(f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}", 40.0)
        ws.set(f"{eid}{WidgetState.ROW_SELECTION_HONOURED_SUFFIX}", "r2")
        ws.set(f"{eid}{WidgetState.FOCUS_SEEN_SUFFIX}", value=True)
        ws.set(f"{eid}{WidgetState.SPLIT_RATIO_SUFFIX}", 0.3)

        snapshot = ws.observable_snapshot()

        assert snapshot == {
            f"{eid}{WidgetState.HONOURED_SUFFIX}": "tab1",
            f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}": 42.0,
            f"{eid}{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}": 40.0,
            f"{eid}{WidgetState.ROW_SELECTION_HONOURED_SUFFIX}": "r2",
            f"{eid}{WidgetState.FOCUS_SEEN_SUFFIX}": True,
            f"{eid}{WidgetState.SPLIT_RATIO_SUFFIX}": 0.3,
        }

    def test_a_frozenset_value_is_narrowed_to_a_sorted_tuple(self) -> None:
        ws = WidgetState()
        ws.set("multiselect", frozenset({"c", "a", "b"}))
        assert ws.observable_snapshot() == {"multiselect": ("a", "b", "c")}

    def test_a_color_pickers_rgba_tuple_is_included_unconverted(self) -> None:
        # RgbaColor.as_tuple() -- a plain tuple[float, ...], not a frozenset --
        # must pass through the snapshot rather than crash the wire narrowing.
        ws = WidgetState()
        ws.set("swatch", (0.1, 0.2, 0.3, 1.0))
        assert ws.observable_snapshot() == {"swatch": (0.1, 0.2, 0.3, 1.0)}

    def test_an_empty_store_yields_an_empty_snapshot(self) -> None:
        assert WidgetState().observable_snapshot() == {}
