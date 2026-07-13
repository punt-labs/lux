"""HubDisplay forgets a scene's frame when the scene's lifetime ends.

The frame map is the one storage collaborator keyed by scene rather than by
element, so it cannot ride the per-element teardown that unwinds index, owners,
roots, and children. HubDisplay must forget the frame on the same two cleanup
paths those collaborators unwind on — a clear (empty ``replace_scene``) and a
connection drop — or the map grows unbounded and holds a stale mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.update import AddElement

_SCENE = SceneId("framed-scene")
_OWNER = ConnectionId("owner-conn")
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
    hub_display.record_frame(_SCENE, _FRAME)
    return hub_display


def test_frame_reverts_to_fallback_after_clear() -> None:
    """An empty ``replace_scene`` (the clear path) forgets the frame."""
    hub_display = _seed_framed_scene()
    assert hub_display.frame_id_for(_SCENE) == _FRAME

    hub_display.replace_scene(_OWNER, _SCENE, ())

    # The scene now holds nothing; the frame reverts to the scene's own id.
    assert hub_display.frame_id_for(_SCENE) == str(_SCENE)


def test_frame_reverts_to_fallback_after_connection_drop() -> None:
    """Dropping the owning connection forgets its scenes' frames."""
    hub_display = _seed_framed_scene()
    assert hub_display.frame_id_for(_SCENE) == _FRAME

    hub_display.drop_connection(_OWNER)

    assert hub_display.frame_id_for(_SCENE) == str(_SCENE)


def test_non_empty_replace_keeps_the_frame() -> None:
    """A re-show (non-empty ``replace_scene``) preserves the recorded frame.

    Only a clear forgets the frame — a re-show keeps it so the scene lands back
    in the frame it was originally shown in.
    """
    hub_display = _seed_framed_scene()

    hub_display.replace_scene(_OWNER, _SCENE, [_WireLeaf(id="fresh")])

    assert hub_display.frame_id_for(_SCENE) == _FRAME
