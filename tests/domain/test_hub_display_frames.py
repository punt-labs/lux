"""HubDisplay keeps a scene's frame until it is blanked away.

A presentation is recorded when a scene is shown. When a scene empties through an
``update`` that removes the last root, a ``drop_connection``, or a direct empty
replace, the frame is kept so the replicator can blank the scene into the frame it
was shown in rather than a default one; the replicator reclaims it once the blank
is delivered. A whole-display clear is the exception: it forgets each scene's
frame up front, because the clear blanks the whole display and needs no per-frame
targeting. A re-show overwrites the frame with the new presentation.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.hub.scene_writer import HubSceneWriter
from punt_lux.domain.hub.write_result import WriteAccepted
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements.text import TextElement

_SCENE = SceneId("framed-scene")
_OWNER = ConnectionId("owner-conn")
_OTHER = ConnectionId("other-conn")
_FRAME = "custom-frame"


@dataclass(frozen=True, slots=True)
class _WireLeaf:
    """Wire-shaped leaf — satisfies the Element Protocol structurally."""

    id: str
    kind: Literal["leaf"] = "leaf"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=str(d["id"]))


def _seed_framed_scene() -> HubDisplay:
    """Install one owned root in ``_SCENE`` and record its custom frame."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    hub_display.apply(
        _OWNER,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="root"), parent_id=None),
    )
    hub_display.record_presentation(_SCENE, ScenePresentation(frame_id=_FRAME))
    return hub_display


def test_frame_persists_after_an_empty_replace() -> None:
    """An empty ``replace_scene`` (update-to-empty) keeps the frame to blank into.

    This is the update path, not the whole-display clear: the store keeps the
    frame so the replicator's blank lands in it, and the replicator reclaims it
    only after the blank is delivered.
    """
    hub_display = _seed_framed_scene()
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME

    hub_display.replace_scene(_OWNER, _SCENE, ())

    # The scene is empty but its frame is kept, so a blank push lands in it.
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME


def test_clear_forgets_each_scenes_frame() -> None:
    """The whole-display clear forgets each emptied scene's frame up front.

    Unlike the update-to-empty path, a clear blanks the whole display and needs no
    per-frame targeting, so it reclaims the presentation immediately — bounding the
    frame map under a churning-id clear workload. A later lookup falls back to the
    self-framed default.
    """
    hub_display = _seed_framed_scene()
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME

    HubSceneWriter(hub_display).clear(_OWNER)

    assert not hub_display.scene_roots(_SCENE)  # emptied
    assert hub_display.presentation_for(_SCENE).frame_id == str(_SCENE)  # forgotten


def test_clear_keeps_the_frame_of_a_scene_a_survivor_still_holds() -> None:
    """A clear forgets only the scenes it leaves empty, not a multi-owner survivor.

    The scene has roots from two connections. When one connection clears, its
    replace empties only its own roots; the other connection's root remains, so the
    scene is not empty and its frame is kept — that survivor's next re-push must
    land in the frame it was shown in. The clear forgets a frame only for a scene it
    actually emptied.
    """
    hub_display = _seed_framed_scene()  # _OWNER holds root "root", frame _FRAME
    hub_display.register_client(_OTHER)
    hub_display.apply(
        _OTHER,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="other"), parent_id=None),
    )

    HubSceneWriter(hub_display).clear(_OWNER)

    # _OWNER's root is gone, _OTHER's survives, so the scene keeps its frame.
    assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"other"}
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME


def test_frame_persists_after_connection_drop() -> None:
    """Dropping the owning connection keeps its scenes' frames for the blank."""
    hub_display = _seed_framed_scene()
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME

    hub_display.drop_connection(_OWNER)

    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME


def test_drop_connection_returns_the_scenes_it_touched() -> None:
    """A9: drop names the departed connection's scenes for the caller to repaint.

    The disconnect entry point marks these dirty so the replicator blanks the
    ones the drop emptied into their frames, and repaints the ones a survivor
    still holds.
    """
    hub_display = _seed_framed_scene()  # _OWNER holds a root in _SCENE
    assert hub_display.drop_connection(_OWNER) == frozenset({_SCENE})


def test_non_empty_replace_keeps_the_frame() -> None:
    """A re-show (non-empty ``replace_scene``) preserves the recorded frame.

    A re-show with the same frame keeps it, so the scene lands back in the frame
    it was originally shown in; a re-show with a new presentation would overwrite
    it. The frame is only dropped when the scene is blanked away — by a clear or by
    the replicator's post-blank reclaim.
    """
    hub_display = _seed_framed_scene()

    hub_display.replace_scene(_OWNER, _SCENE, [_WireLeaf(id="fresh")])

    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME


def test_dropping_one_owner_keeps_frame_while_another_holds_a_root() -> None:
    """Dropping one owner of a shared scene does not forget the frame.

    The scene has two roots from two connections. Dropping the first must not
    take the frame with it — the second connection's root is still live and its
    next re-push would land in the wrong frame if the association were gone.
    This is the over-eviction guard: forget keys on the scene's roots, not on
    which scenes the dropped connection happened to touch.
    """
    hub_display = _seed_framed_scene()  # _OWNER holds root "root"
    hub_display.register_client(_OTHER)
    hub_display.apply(
        _OTHER,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="other"), parent_id=None),
    )

    hub_display.drop_connection(_OWNER)

    # _OTHER's root survives, so the frame association survives with it.
    assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"other"}
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME


def test_dropping_a_child_only_owner_keeps_frame() -> None:
    """Dropping a connection that owns only a child leaves the frame intact.

    The connection owns no root in the scene, so the scene still has its root
    after the drop. A frame forget keyed on "scenes this connection touched"
    would wrongly evict here; keyed on remaining roots, it does not.
    """
    hub_display = _seed_framed_scene()  # _OWNER holds root "root"
    hub_display.register_client(_OTHER)
    hub_display.apply(
        _OTHER,
        AddElement(
            scene_id=_SCENE,
            element=_WireLeaf(id="child"),
            parent_id=ElementId("root"),
        ),
    )

    hub_display.drop_connection(_OTHER)

    # The root remains, so the frame is kept.
    assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"root"}
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME


def test_removing_last_root_via_update_keeps_the_frame() -> None:
    """Removing a scene's last root through ``update`` keeps the frame to blank into.

    The scene ends empty, but its presentation is kept, so the replicator's next
    resend blanks it into the frame it was shown in rather than a default one.
    """
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    text = TextElement(id="t1", content="hello")
    hub_display.apply(_OWNER, AddElement(scene_id=_SCENE, element=text, parent_id=None))
    hub_display.record_presentation(_SCENE, ScenePresentation(frame_id=_FRAME))
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME

    result = HubSceneWriter(hub_display).apply(
        _OWNER, _SCENE, [{"id": "t1", "remove": True}]
    )

    assert isinstance(result, WriteAccepted)
    assert not hub_display.scene_roots(_SCENE)
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME


def test_show_scene_commits_roots_and_frame_under_one_lock() -> None:
    """show_scene commits the new roots and the new frame in one write region.

    A concurrent snapshot must never pair the new roots with the old frame, or the
    reverse. Holding the store lock blocks the whole show_scene: while it is held
    neither the roots nor the frame have moved, and on release both flip together.
    """
    hub_display = _seed_framed_scene()  # root "root", frame _FRAME
    committed = threading.Event()

    def reshow() -> None:
        hub_display.show_scene(
            _OWNER,
            _SCENE,
            [_WireLeaf(id="fresh")],
            ScenePresentation(frame_id="new-frame"),
        )
        committed.set()

    with hub_display.write_lock():  # the reshow cannot commit while this is held
        worker = threading.Thread(target=reshow)
        worker.start()
        assert not committed.wait(0.3)  # provably blocked on the store lock
        # Neither half has changed: old root and old frame both still present.
        assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"root"}
        assert hub_display.presentation_for(_SCENE).frame_id == _FRAME
    assert committed.wait(2.0)  # lock released; the reshow commits both together
    worker.join(timeout=2.0)
    assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"fresh"}
    assert hub_display.presentation_for(_SCENE).frame_id == "new-frame"
