"""Unit tests for ``SceneInspector`` — the enriched inspect_scene handler.

The integration path (through a real ``DisplayServer``) lives in
``test_scene_inspection.py``. These isolate the collaborator: a real
``SceneManager`` supplies the element objects and a real (empty) domain
``Display`` supplies mirror presence.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.display import Display
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import TextElement
from punt_lux.scene import SceneManager
from punt_lux.scene_inspector import SceneInspector


def _scene_manager_with(scene: SceneMessage) -> SceneManager:
    sm = SceneManager(on_scene_replaced=lambda _ids: None)
    sm._scenes[scene.id] = scene
    return sm


def test_inspect_reads_element_types_and_empty_mirror() -> None:
    sm = _scene_manager_with(
        SceneMessage(id="s1", elements=[TextElement(id="t1", content="hi")])
    )
    result = SceneInspector(scene_manager=sm, domain_display=Display()).inspect("s1")
    rec = result["element_paths"][0]
    assert rec["render_path"] == "abc"
    # an empty domain Display mirror means the element is not (yet) present
    assert rec["domain_mirror_present"] is False


def test_inspect_missing_scene_raises_lookup_error() -> None:
    inspector = SceneInspector(
        scene_manager=SceneManager(on_scene_replaced=lambda _ids: None),
        domain_display=Display(),
    )
    with pytest.raises(LookupError, match="ghost"):
        inspector.inspect("ghost")
