"""Unit tests for PatchApplier — the scene patch-batch collaborator.

Drive :class:`PatchApplier` directly, in isolation from ``SceneManager``: a
shared :class:`SceneTreeWalk` locates targets, a plain set stands in for the
manager's dirty-windows set. These tests own the collaborator's contract
(set, remove, unknown-field rejection, value rejection, widget-state sync,
dirty-window marking, unreachable warning); ``test_scene_manager`` owns the
same behaviors seen through ``apply_update``.
"""

from __future__ import annotations

import math

import pytest

from punt_lux.protocol import (
    ColorPickerElement,
    GroupElement,
    InputNumberElement,
    Patch,
    SceneMessage,
    SliderElement,
    TextElement,
    UpdateMessage,
    WindowElement,
)
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.scene.element_walk import SceneTreeWalk
from punt_lux.scene.patch_applier import PatchApplier
from punt_lux.scene.widget_state import WidgetState


def _make_applier() -> tuple[PatchApplier, set[str]]:
    """Build a PatchApplier over a fresh walk and dirty-windows set."""
    dirty: set[str] = set()
    applier = PatchApplier(walk=SceneTreeWalk(), dirty_windows=dirty)
    return applier, dirty


def _scene(*elements: object) -> SceneMessage:
    """Wrap elements in a single unframed scene message."""
    return SceneMessage(id="s1", elements=list(elements))  # type: ignore[arg-type]


def _update(*patches: Patch) -> UpdateMessage:
    """Wrap patches in an update targeting scene ``s1``."""
    return UpdateMessage(scene_id="s1", patches=list(patches))


class TestApplySet:
    def test_set_patch_modifies_field(self) -> None:
        """A set-patch rebinds the located legacy element's field."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Original"))

        applier.apply(scene, _update(Patch(id="t1", set={"content": "New"})), None)

        elem = scene.elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "New"

    def test_set_patch_reaches_child_in_abc_group(self) -> None:
        """A set-patch descends an all-ABC group to patch a nested child."""
        applier, _ = _make_applier()
        group = GroupElement(
            id="g1",
            layout="rows",
            children=(TextElement(id="t1", content="Original"),),
        )
        scene = _scene(group)

        applier.apply(scene, _update(Patch(id="t1", set={"content": "Updated"})), None)

        stored = scene.elements[0]
        assert isinstance(stored, GroupElement)
        child = stored.children[0]
        assert isinstance(child, TextElement)
        assert child.content == "Updated"

    def test_id_and_kind_are_never_patched(self) -> None:
        """``id`` and ``kind`` are silently dropped, not applied nor rejected."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        applier.apply(
            scene, _update(Patch(id="t1", set={"id": "t999", "kind": "button"})), None
        )

        elem = scene.elements[0]
        assert elem.id == "t1"
        assert elem.kind == "text"


class TestApplyRemove:
    def test_remove_drops_element(self) -> None:
        """A remove-patch pops the element out of the scene."""
        applier, _ = _make_applier()
        scene = _scene(
            TextElement(id="t1", content="Keep"),
            TextElement(id="t2", content="Gone"),
        )

        applier.apply(scene, _update(Patch(id="t2", remove=True)), None)

        ids = [getattr(e, "id", None) for e in scene.elements]
        assert ids == ["t1"]

    def test_remove_clears_widget_state(self) -> None:
        """Removing an element clears its cached widget state."""
        applier, _ = _make_applier()
        scene = _scene(SliderElement(id="sl1", label="Vol", value=0.5))
        ws = WidgetState()
        ws.set("sl1", 0.5)

        applier.apply(scene, _update(Patch(id="sl1", remove=True)), ws)

        # _remove_located writes None over the removed id's cached value.
        assert ws.get("sl1") is None


class TestUnknownFields:
    def test_unknown_field_raises(self) -> None:
        """A structural error — an unknown field — propagates as ValueError."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        with pytest.raises(ValueError, match="bogus"):
            applier.apply(
                scene,
                _update(Patch(id="t1", set={"content": "x", "bogus": 1})),
                None,
            )

    def test_all_unknown_fields_raises(self) -> None:
        """A patch of only unknown fields still raises."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        with pytest.raises(ValueError, match="nope"):
            applier.apply(scene, _update(Patch(id="t1", set={"nope": 1})), None)


class TestRejectedValue:
    """A validated setter's rejection is a per-patch no-op, never a crash."""

    def test_out_of_range_value_is_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An out-of-range ``fraction`` is caught, logged, and skipped."""
        applier, _ = _make_applier()
        scene = _scene(ProgressElement(id="p1", fraction=0.25))

        with caplog.at_level("WARNING"):
            applier.apply(scene, _update(Patch(id="p1", set={"fraction": 1.5})), None)

        elem = scene.elements[0]
        assert isinstance(elem, ProgressElement)
        assert elem.fraction == 0.25
        assert any(
            "rejected" in r.message and "p1" in r.message for r in caplog.records
        )

    def test_nan_value_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """A NaN ``fraction`` is skipped the same way."""
        applier, _ = _make_applier()
        scene = _scene(ProgressElement(id="p1", fraction=0.25))

        with caplog.at_level("WARNING"):
            applier.apply(
                scene, _update(Patch(id="p1", set={"fraction": math.nan})), None
            )

        elem = scene.elements[0]
        assert isinstance(elem, ProgressElement)
        assert elem.fraction == 0.25

    def test_rejected_patch_does_not_abort_later_patches(self) -> None:
        """One rejected patch does not block the patches after it in the batch."""
        applier, _ = _make_applier()
        scene = _scene(
            ProgressElement(id="p1", fraction=0.25),
            TextElement(id="t1", content="before"),
        )

        applier.apply(
            scene,
            _update(
                Patch(id="p1", set={"fraction": 1.5}),
                Patch(id="t1", set={"content": "after"}),
            ),
            None,
        )

        first, second = scene.elements
        assert isinstance(first, ProgressElement)
        assert first.fraction == 0.25
        assert isinstance(second, TextElement)
        assert second.content == "after"


class TestWidgetStateSync:
    def test_value_patch_mirrors_into_widget_state(self) -> None:
        """A value-bearing input writes its post-patch value into WidgetState."""
        applier, _ = _make_applier()
        scene = _scene(InputNumberElement(id="in1", label="N", value=1.0))
        ws = WidgetState()

        applier.apply(scene, _update(Patch(id="in1", set={"value": 42.0})), ws)

        assert ws.get("in1") == 42.0

    def test_value_patch_on_color_picker_discards_widget_state(self) -> None:
        """A kind excluded from the value dispatch has its cache discarded."""
        applier, _ = _make_applier()
        scene = _scene(ColorPickerElement(id="cp1", label="Tint", value="#FF0000"))
        ws = WidgetState()
        ws.set("cp1", (1.0, 0.0, 0.0, 1.0))

        applier.apply(scene, _update(Patch(id="cp1", set={"value": "#00FF00"})), ws)

        sentinel = object()
        assert ws.get("cp1", sentinel) is sentinel


class TestDirtyWindows:
    def test_position_patch_marks_window_dirty(self) -> None:
        """A moved window is added to the shared dirty-windows set."""
        applier, dirty = _make_applier()
        scene = _scene(WindowElement(id="w1", title="Panel", children=[]))

        applier.apply(scene, _update(Patch(id="w1", set={"x": 10, "y": 20})), None)

        assert "w1" in dirty


class TestUnreachablePatch:
    def test_absent_target_is_silent_noop(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A patch for a truly-absent id is a normal no-op, no warning."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        with caplog.at_level("WARNING"):
            applier.apply(scene, _update(Patch(id="ghost", set={"content": "x"})), None)

        assert scene.elements[0].content == "Hello"  # type: ignore[union-attr]
        assert not any("unreachable" in r.message for r in caplog.records)
