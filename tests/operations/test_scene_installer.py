"""SceneInstaller — a scene leaving a frame has the frame's survivors resent."""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.protocol.elements.text import TextElement

_OWNER = ConnectionId("c1")


@final
class _Marks:
    """Records the scenes the installer marks dirty, in order."""

    marked: list[SceneId]
    __slots__ = ("marked",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.marked = []
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.marked.append(scene_id)

    def mark_menus(self) -> None:
        """Menus are not what an install changes."""


def _show(installer: SceneInstaller, marks: _Marks, scene: str, frame: str) -> None:
    marks.marked.clear()
    submission = SceneSubmission.of(
        [TextElement(id="t", content="x")],
        scene,
        ScenePresentation(frame_id=frame),
        None,
    )
    installer.install(submission, owner=_OWNER)


def _scoped(local: str) -> SceneId:
    return SceneId(f"{_OWNER}\x1f{local}")


def _installed() -> tuple[SceneInstaller, _Marks]:
    marks = _Marks()
    installer = SceneInstaller(HubDisplay(), marks)
    for scene in ("s1", "s2"):
        _show(installer, marks, scene, "shared")
    return installer, marks


def test_a_scene_moved_out_of_a_frame_has_its_survivors_resent() -> None:
    installer, marks = _installed()

    _show(installer, marks, "s1", "elsewhere")

    assert set(marks.marked) == {_scoped("s1"), _scoped("s2")}


def test_a_re_show_in_the_same_frame_marks_only_the_scene() -> None:
    installer, marks = _installed()

    _show(installer, marks, "s1", "shared")

    assert marks.marked == [_scoped("s1")]


def test_a_first_show_marks_only_the_scene() -> None:
    installer, marks = _installed()

    _show(installer, marks, "s3", "fresh")

    assert marks.marked == [_scoped("s3")]


def test_a_scene_moved_out_of_a_frame_it_sat_in_alone_marks_only_itself() -> None:
    installer, marks = _installed()
    _show(installer, marks, "s3", "solo")

    _show(installer, marks, "s3", "elsewhere")

    assert marks.marked == [_scoped("s3")]
