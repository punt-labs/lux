"""HubDisplay forgets a scene's frame on exactly one criterion — no roots left.

The frame map is the one storage collaborator keyed by scene rather than by
element, so it cannot ride the per-element teardown that unwinds index, owners,
roots, and children. HubDisplay forgets the frame through ``maybe_forget_frame``,
which drops it iff no root remains, checked uniformly after every teardown path:
an empty ``replace_scene`` (clear), a ``drop_connection``, and a direct remove of
the last root through ``update``.

Keying on the scene's own roots, not on which scenes a connection touched, is
what keeps a shared scene's frame alive while any owner still holds a root in
it — and what closes the leak when the last root leaves by the ``update``
remove path, which rides neither clear nor disconnect.
"""

from __future__ import annotations

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


def test_frame_reverts_to_fallback_after_clear() -> None:
    """An empty ``replace_scene`` (the clear path) forgets the frame."""
    hub_display = _seed_framed_scene()
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME

    hub_display.replace_scene(_OWNER, _SCENE, ())

    # The scene now holds nothing; the frame reverts to the scene's own id.
    assert hub_display.presentation_for(_SCENE).frame_id == str(_SCENE)


def test_frame_reverts_to_fallback_after_connection_drop() -> None:
    """Dropping the owning connection forgets its scenes' frames."""
    hub_display = _seed_framed_scene()
    assert hub_display.presentation_for(_SCENE).frame_id == _FRAME

    hub_display.drop_connection(_OWNER)

    assert hub_display.presentation_for(_SCENE).frame_id == str(_SCENE)


def test_non_empty_replace_keeps_the_frame() -> None:
    """A re-show (non-empty ``replace_scene``) preserves the recorded frame.

    Only a clear forgets the frame — a re-show keeps it so the scene lands back
    in the frame it was originally shown in.
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


def test_removing_last_root_via_update_forgets_the_frame() -> None:
    """Removing a scene's last root through the ``update`` path forgets the frame.

    The remove/patch path rides neither the clear nor the disconnect teardown,
    so before the uniform criterion it stranded the frame. Now the writer offers
    the scene up after its removals: the last root gone, the frame reverts to the
    scene's own id.
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
    assert hub_display.presentation_for(_SCENE).frame_id == str(_SCENE)
