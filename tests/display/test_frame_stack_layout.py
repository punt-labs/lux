"""``_render_frame_stack`` — the collapsed-scene outer-walk gate (lux-qfzu.5).

The outer scene walk in stack layout already gates every per-scene render
cost — element painting, the widget-state swap, the paint-clock stamp, the
geometry scene entry — behind the same ``collapsing_header`` return that
gates the section body: a closed header skips ``_render_framed_scene``
entirely, so ``elem.render()`` never fires for it. These tests lock that
property in against regression.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display import RenderLoop
from punt_lux.display.replica.frame import Frame
from punt_lux.protocol import SceneMessage


class _DefaultOpenFlag:
    value = 1


class _TreeNodeFlags:
    default_open = _DefaultOpenFlag()


class FakeStackImgui:
    """A ``collapsing_header`` stand-in whose open/closed state the test drives."""

    def __init__(self, open_scene_ids: set[str]) -> None:
        self.TreeNodeFlags_ = _TreeNodeFlags()
        self._open_scene_ids = open_scene_ids

    def collapsing_header(self, label: str, *, flags: int = 0) -> bool:
        _ = flags
        scene_id = label.rsplit("##", 1)[1]
        return scene_id in self._open_scene_ids

    def push_id(self, scene_id: str) -> None:
        _ = scene_id

    def pop_id(self) -> None:
        pass


def _make_server() -> RenderLoop:
    return RenderLoop("/tmp/test-lux-frame-stack.sock")


def _stack_frame(scene_ids: list[str]) -> tuple[Frame, dict[str, MagicMock]]:
    elements = {scene_id: MagicMock(id=f"{scene_id}-elem") for scene_id in scene_ids}
    scenes = {
        scene_id: SceneMessage(
            id=scene_id, elements=[elements[scene_id]], frame_id="f1"
        )
        for scene_id in scene_ids
    }
    frame = Frame(
        frame_id="f1",
        title="Stack",
        owner_fds=set(),
        scenes=scenes,
        scene_order=list(scene_ids),
        layout="stack",
    )
    return frame, elements


class TestStackLayoutOuterWalk:
    def test_three_collapsed_scenes_render_nothing(self) -> None:
        server = _make_server()
        frame, elements = _stack_frame(["s1", "s2", "s3"])

        server._render_frame_stack(frame, FakeStackImgui(open_scene_ids=set()))

        for elem in elements.values():
            elem.render.assert_not_called()

    def test_opening_one_exposes_it_on_the_next_frame(self) -> None:
        server = _make_server()
        frame, elements = _stack_frame(["s1", "s2", "s3"])
        server._render_frame_stack(frame, FakeStackImgui(open_scene_ids=set()))

        server._render_frame_stack(frame, FakeStackImgui(open_scene_ids={"s2"}))

        elements["s1"].render.assert_not_called()
        elements["s2"].render.assert_called_once()
        elements["s3"].render.assert_not_called()

    def test_toggling_closed_again_stops_rendering_it(self) -> None:
        server = _make_server()
        frame, elements = _stack_frame(["s1", "s2", "s3"])
        server._render_frame_stack(frame, FakeStackImgui(open_scene_ids={"s2"}))
        elements["s2"].render.assert_called_once()

        server._render_frame_stack(frame, FakeStackImgui(open_scene_ids=set()))

        elements["s2"].render.assert_called_once()  # unchanged — no second call
