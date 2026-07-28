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
from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
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
    hub_display.frames.record(_SCENE, ScenePresentation(frame_id=_FRAME))
    return hub_display


def test_frame_persists_after_an_empty_replace() -> None:
    """An empty ``replace_scene`` (update-to-empty) keeps the frame to blank into.

    This is the update path, not the whole-display clear: the store keeps the
    frame so the replicator's blank lands in it, and the replicator reclaims it
    only after the blank is delivered.
    """
    hub_display = _seed_framed_scene()
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME

    hub_display.replace_scene(_OWNER, _SCENE, ())

    # The scene is empty but its frame is kept, so a blank push lands in it.
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


def test_clear_keeps_each_emptied_scenes_frame_for_the_replicator_to_blank() -> None:
    """A clear empties each scene but keeps its frame, exactly like update-to-empty.

    The clear routes each emptied scene through the replicator's per-scene blank
    (not a whole-display wipe), so the presentation must survive: the replicator
    blanks the scene into the frame it was shown in, then reclaims the frame once
    the blank lands. Forgetting it here would strand a custom frame — the blank
    would target a frame guessed from the scene id — so the writer leaves reclaim
    to the replicator's post-blank step.
    """
    hub_display = _seed_framed_scene()
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME

    touched = HubSceneWriter(hub_display).clear(_OWNER)

    assert touched == frozenset({_SCENE})
    assert not hub_display.scene_roots(_SCENE)  # emptied
    # kept — the empty-push blanks this real frame, not the self-framed default
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


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
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


def test_frame_persists_after_connection_drop() -> None:
    """Dropping the owning connection keeps its scenes' frames — the UI survives."""
    hub_display = _seed_framed_scene()
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME

    hub_display.drop_connection(_OWNER)

    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


def test_drop_connection_leaves_the_scenes_standing() -> None:
    """A9: a session's scenes survive its disconnect — only the client is forgotten.

    The connection's roots stay installed and owned by its id (so a later frame
    close, clear, or TTL can remove them); only the Hub-client registration goes.
    """
    hub_display = _seed_framed_scene()  # _OWNER holds a root in _SCENE
    hub_display.drop_connection(_OWNER)
    assert hub_display.scene_roots(_SCENE)
    assert not hub_display.is_client(_OWNER)


def test_remove_frame_tears_down_its_scenes() -> None:
    """Closing a frame removes the scenes it held; both tiers agree it is gone."""
    hub_display = _seed_framed_scene()
    touched = hub_display.frames.remove_frame(_FRAME)
    assert touched == frozenset({_SCENE})
    assert hub_display.scene_roots(_SCENE) == []


def test_remove_frame_removes_a_scene_whose_owner_departed() -> None:
    """A frame close still works after the owning session left.

    Scenes outlive their session; the close tears down each root through the
    remover regardless of the (now-departed) owner, so an orphaned frame closes.
    """
    hub_display = _seed_framed_scene()
    hub_display.drop_connection(_OWNER)  # session gone, scene stands
    touched = hub_display.frames.remove_frame(_FRAME)
    assert touched == frozenset({_SCENE})
    assert hub_display.scene_roots(_SCENE) == []


def test_remove_frame_of_an_unknown_frame_touches_nothing() -> None:
    assert HubDisplay().frames.remove_frame("ghost") == frozenset()


def test_non_empty_replace_keeps_the_frame() -> None:
    """A re-show (non-empty ``replace_scene``) preserves the recorded frame.

    A re-show with the same frame keeps it, so the scene lands back in the frame
    it was originally shown in; a re-show with a new presentation would overwrite
    it. The frame is only dropped when the scene is blanked away — by a clear or by
    the replicator's post-blank reclaim.
    """
    hub_display = _seed_framed_scene()

    hub_display.replace_scene(_OWNER, _SCENE, [_WireLeaf(id="fresh")])

    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


def test_dropping_one_owner_keeps_both_roots_of_a_shared_scene() -> None:
    """Dropping a connection removes none of its roots — the UI survives.

    The scene has two roots from two connections. Dropping the first tears down
    nothing: both roots and the frame association survive, to be removed later
    only by an explicit act (frame close, clear, TTL), never by the disconnect.
    """
    hub_display = _seed_framed_scene()  # _OWNER holds root "root"
    hub_display.register_client(_OTHER)
    hub_display.apply(
        _OTHER,
        AddElement(scene_id=_SCENE, element=_WireLeaf(id="other"), parent_id=None),
    )

    hub_display.drop_connection(_OWNER)

    assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"root", "other"}
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


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
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


def test_removing_last_root_via_update_keeps_the_frame() -> None:
    """Removing a scene's last root through ``update`` keeps the frame to blank into.

    The scene ends empty, but its presentation is kept, so the replicator's next
    resend blanks it into the frame it was shown in rather than a default one.
    """
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    text = TextElement(id="t1", content="hello")
    hub_display.apply(_OWNER, AddElement(scene_id=_SCENE, element=text, parent_id=None))
    hub_display.frames.record(_SCENE, ScenePresentation(frame_id=_FRAME))
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME

    result = HubSceneWriter(hub_display).apply(
        SceneScope(_OWNER, _SCENE), [{"id": "t1", "remove": True}]
    )

    assert isinstance(result, WriteAccepted)
    assert not hub_display.scene_roots(_SCENE)
    assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME


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
        assert hub_display.frames.presentation_for(_SCENE).frame_id == _FRAME
    assert committed.wait(2.0)  # lock released; the reshow commits both together
    worker.join(timeout=2.0)
    assert {e.id for e in hub_display.scene_roots(_SCENE)} == {"fresh"}
    assert hub_display.frames.presentation_for(_SCENE).frame_id == "new-frame"
