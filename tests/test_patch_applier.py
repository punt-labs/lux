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
from punt_lux.scene.manager import SceneManager
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
    """A structural error — an unknown field — is a per-patch no-op, never a crash."""

    def test_unknown_field_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unknown field alongside a known one skips the whole set-patch, logged.

        The applier surfaces the structural error instead of raising it, so the
        element keeps its value and the batch continues. Skipping the whole
        patch (not just the bad field) keeps a mixed set-patch atomic.
        """
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        with caplog.at_level("WARNING"):
            applier.apply(
                scene,
                _update(Patch(id="t1", set={"content": "x", "bogus": 1})),
                None,
            )

        elem = scene.elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "Hello"
        assert any(
            "unknown field" in r.message and "t1" in r.message for r in caplog.records
        )

    def test_all_unknown_fields_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """A patch of only unknown fields is logged and skipped, never raised."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        with caplog.at_level("WARNING"):
            applier.apply(scene, _update(Patch(id="t1", set={"nope": 1})), None)

        assert scene.elements[0].content == "Hello"  # type: ignore[union-attr]
        assert any("unknown field" in r.message for r in caplog.records)


class TestMalformedPatch:
    """A patch naming neither a removal nor any fields is a safe no-op."""

    def test_empty_set_is_noop(self) -> None:
        """A patch with an empty ``set`` mutation changes nothing and never raises."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        applier.apply(scene, _update(Patch(id="t1", set={})), None)

        assert scene.elements[0].content == "Hello"  # type: ignore[union-attr]

    def test_neither_set_nor_remove_is_noop(self) -> None:
        """A patch that neither sets fields nor removes is a safe no-op."""
        applier, _ = _make_applier()
        scene = _scene(TextElement(id="t1", content="Hello"))

        applier.apply(scene, _update(Patch(id="t1")), None)

        assert scene.elements[0].content == "Hello"  # type: ignore[union-attr]


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


class TestPatchRejectionPartition:
    """The full patch-rejection case space, driven through ``apply_update``.

    Enumerates every way a progress ``fraction`` patch is rejected — out of
    range (``ValueError``), NaN (``ValueError``), non-number (``TypeError``),
    bool (``TypeError``) — plus the structural unknown-field error, the
    absent-id no-op, and multi-field atomicity. Every case asserts the batch
    survives: no crash, the target unchanged, the rejection logged where
    applicable, and a valid patch elsewhere in the same batch still applies.
    An unknown field is surfaced per patch (logged, skipped) rather than
    propagated, so a structural error never terminates the message loop.

    Unlike the ``PatchApplier``-in-isolation tests above, these drive the real
    ``SceneManager.apply_update`` so the whole scene-patch path — resolve,
    walk, apply, reject, log — is exercised end to end.
    """

    @staticmethod
    def _manager() -> SceneManager:
        """Build a manager holding one progress and one text element."""
        manager = SceneManager(on_scene_replaced=lambda _ids: None)
        scene = SceneMessage(
            id="s1",
            elements=[
                ProgressElement(id="p1", fraction=0.25),
                TextElement(id="t1", content="before"),
            ],
        )
        manager.handle_scene(scene, owner_fd=1)
        return manager

    @staticmethod
    def _progress(manager: SceneManager) -> ProgressElement:
        elem = manager.scenes["s1"].elements[0]
        assert isinstance(elem, ProgressElement)
        return elem

    @staticmethod
    def _text(manager: SceneManager) -> TextElement:
        elem = manager.scenes["s1"].elements[1]
        assert isinstance(elem, TextElement)
        return elem

    @pytest.mark.parametrize(
        ("bad_value", "log_fragment"),
        [
            pytest.param(1.5, "in [0, 1]", id="out-of-range-high"),
            pytest.param(-0.5, "in [0, 1]", id="out-of-range-low"),
            pytest.param(math.nan, "in [0, 1]", id="nan"),
            pytest.param("fast", "must be a number", id="non-number"),
            pytest.param(True, "must be a number", id="bool"),
        ],
    )
    def test_rejected_fraction_is_a_survivable_noop(
        self,
        bad_value: object,
        log_fragment: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A rejected fraction — value or type — is a logged, non-fatal no-op."""
        manager = self._manager()
        update = UpdateMessage(
            scene_id="s1",
            patches=[
                Patch(id="p1", set={"fraction": bad_value}),
                Patch(id="t1", set={"content": "after"}),
            ],
        )

        with caplog.at_level("WARNING"):
            manager.apply_update(update)  # (a) returns normally — no crash

        assert self._progress(manager).fraction == 0.25  # (b) target unchanged
        assert any(  # (c) the right rejection was logged for p1
            "rejected" in r.message and "p1" in r.message and log_fragment in r.message
            for r in caplog.records
        )
        assert self._text(manager).content == "after"  # (d) valid patch applied

    def test_unknown_field_is_logged_not_raised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown field is a structural no-op: logged, unchanged, never raised.

        The applier surfaces the structural error at the boundary rather than
        letting it propagate through ``apply_update`` to the display's message
        loop, so the target keeps its value and the loop stays alive.
        """
        manager = self._manager()
        update = UpdateMessage(
            scene_id="s1", patches=[Patch(id="p1", set={"bogus": 1})]
        )

        with caplog.at_level("WARNING"):
            manager.apply_update(update)

        assert self._progress(manager).fraction == 0.25
        assert any(
            "unknown field" in r.message and "p1" in r.message for r in caplog.records
        )

    def test_unknown_field_does_not_strand_later_patches(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A surfaced unknown-field error still lets later patches in the batch apply.

        Batch = [unknown-field set on p1, valid set on t1]: p1 is skipped and
        t1 still updates, so one structural error never abandons the rest of
        the batch.
        """
        manager = self._manager()
        update = UpdateMessage(
            scene_id="s1",
            patches=[
                Patch(id="p1", set={"bogus": 1}),
                Patch(id="t1", set={"content": "after"}),
            ],
        )

        with caplog.at_level("WARNING"):
            manager.apply_update(update)

        assert self._progress(manager).fraction == 0.25
        assert self._text(manager).content == "after"

    def test_remove_of_absent_id_is_a_safe_noop(self) -> None:
        """Removing an id not in the scene changes nothing and never raises.

        The tree walk finds no location, so the patch is skipped; a truly-absent
        target is a normal no-op, so both existing elements survive.
        """
        manager = self._manager()
        update = UpdateMessage(scene_id="s1", patches=[Patch(id="ghost", remove=True)])

        manager.apply_update(update)

        assert self._progress(manager).fraction == 0.25
        assert self._text(manager).content == "before"

    def test_multi_field_patch_is_atomic(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A rejected multi-field patch leaves BOTH fields unchanged.

        ``label`` precedes ``fraction`` in dict order; a naive setter loop would
        apply ``label`` before ``fraction`` raises. Base-level rollback restores
        both, so the logged "keeps its previous value" claim is literally true.
        """
        manager = self._manager()
        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="p1", set={"label": "new", "fraction": 1.5})],
        )

        with caplog.at_level("WARNING"):
            manager.apply_update(update)

        progress = self._progress(manager)
        assert progress.fraction == 0.25  # unchanged
        assert progress.label == ""  # label NOT applied — atomic rollback
        assert any("rejected" in r.message for r in caplog.records)

    def test_multi_field_rejection_mid_batch_preserves_neighbors(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A valid patch before AND after the atomic-reject patch both apply."""
        manager = self._manager()
        update = UpdateMessage(
            scene_id="s1",
            patches=[
                Patch(id="t1", set={"content": "first"}),
                Patch(id="p1", set={"label": "new", "fraction": 1.5}),
                Patch(id="p1", set={"label": "later"}),
            ],
        )

        with caplog.at_level("WARNING"):
            manager.apply_update(update)

        progress = self._progress(manager)
        assert progress.fraction == 0.25  # the reject patch rolled back fully
        assert progress.label == "later"  # the later valid patch still applied
        assert self._text(manager).content == "first"  # the earlier one too
