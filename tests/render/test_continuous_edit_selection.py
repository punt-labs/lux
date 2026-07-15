"""ContinuousEditArbiter — the carrier-agnostic honour/defer/commit/echo flow.

The three render suites exercise the arbiter through each element's accessor;
this suite tests the shared control flow directly. A ``_SpyAccessor`` proves the
only two carrier-typed touches are ``read`` (the editing-branch buffer) and
``coerce`` (the committed return): every other branch — idle honour, the
commit-echo window, the commit-hub marker, forget-on-move, release — runs
through the untyped WidgetState slots and never calls the accessor.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.display.renderers.imgui.continuous_edit_accessors import StrValueAccessor
from punt_lux.display.renderers.imgui.continuous_edit_selection import (
    ContinuousEditArbiter,
)
from punt_lux.scene.widget_state import WidgetState


@final
class _SpyAccessor:
    """Accessor that records which delegated touch fired, to pin the two seams."""

    reads: int
    coerces: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.reads = 0
        self.coerces = 0
        return self

    def read(self, state: WidgetState, key: str, hub_value: str) -> str:
        self.reads += 1
        return state.get_str(key)

    def coerce(self, stored: object) -> str:
        self.coerces += 1
        return str(stored)


def _arb(state: WidgetState, element_id: str) -> ContinuousEditArbiter[str]:
    return ContinuousEditArbiter(state, element_id, StrValueAccessor())


class TestHonourDefer:
    def test_idle_honours_the_hub_value(self) -> None:
        assert _arb(WidgetState(), "e").resolve("abc") == "abc"

    def test_idle_tracks_the_latest_hub_value(self) -> None:
        arb = _arb(WidgetState(), "e")
        assert arb.resolve("abc") == "abc"
        assert arb.resolve("xyz") == "xyz"

    def test_editing_defers_to_the_buffer(self) -> None:
        arb = _arb(WidgetState(), "e")
        arb.observe(edited=True, value="hel")
        assert arb.resolve("ZZZ") == "hel"

    def test_focus_without_edit_keeps_honouring(self) -> None:
        arb = _arb(WidgetState(), "e")
        arb.observe(edited=False, value="abc")
        assert arb.resolve("xyz") == "xyz"

    def test_release_returns_to_honouring_the_hub(self) -> None:
        arb = _arb(WidgetState(), "e")
        arb.observe(edited=True, value="draft")
        arb.release()
        assert arb.resolve("hub") == "hub"

    def test_slots_are_id_scoped(self) -> None:
        ws = WidgetState()
        _arb(ws, "a").observe(edited=True, value="aaa")
        assert _arb(ws, "a").resolve("x") == "aaa"
        assert _arb(ws, "b").resolve("y") == "y"


class TestCommitEcho:
    def test_commit_is_honoured_until_the_hub_value_moves(self) -> None:
        arb = _arb(WidgetState(), "e")
        arb.commit("hello", hub_value="")
        assert arb.resolve("") == "hello"
        assert arb.resolve("") == "hello"

    def test_commit_clears_once_the_hub_moves_off_the_commit_marker(self) -> None:
        arb = _arb(WidgetState(), "e")
        arb.commit("hello", hub_value="")
        assert arb.resolve("hello") == "hello"  # echo landed: Hub == committed
        assert arb.resolve("other") == "other"  # record gone: honour the Hub

    def test_agent_override_off_the_marker_drops_the_committed_value(self) -> None:
        # The commit-hub marker is load-bearing: honour the commit only while the
        # Hub still reads the value observed at commit time, not "hub != committed".
        arb = _arb(WidgetState(), "e")
        arb.commit("v1", hub_value="old")
        assert arb.resolve("old") == "v1"
        assert arb.resolve("v2") == "v2"

    def test_editing_wins_over_a_pending_commit(self) -> None:
        arb = _arb(WidgetState(), "e")
        arb.commit("hello", hub_value="")
        arb.observe(edited=True, value="fresh")
        assert arb.resolve("") == "fresh"


class TestRemoval:
    def test_discard_for_clears_the_buffer_and_commit_echo(self) -> None:
        ws = WidgetState()
        arb = _arb(ws, "e")
        arb.observe(edited=True, value="draft")
        arb.commit("draft", hub_value="")
        ws.discard_for("e")
        assert _arb(ws, "e").resolve("fresh") == "fresh"


class TestAccessorSeams:
    def test_only_the_editing_branch_calls_read(self) -> None:
        ws = WidgetState()
        spy = _SpyAccessor()
        arb = ContinuousEditArbiter(ws, "e", spy)

        arb.resolve("idle")  # idle: no accessor touch
        assert (spy.reads, spy.coerces) == (0, 0)

        arb.observe(edited=True, value="buf")
        arb.resolve("ignored")  # editing: read fires, coerce does not
        assert (spy.reads, spy.coerces) == (1, 0)

    def test_only_the_committed_return_calls_coerce(self) -> None:
        ws = WidgetState()
        spy = _SpyAccessor()
        arb = ContinuousEditArbiter(ws, "e", spy)
        arb.commit("done", hub_value="pre")

        arb.resolve("pre")  # commit-echo window: coerce fires, read does not
        assert (spy.reads, spy.coerces) == (0, 1)
