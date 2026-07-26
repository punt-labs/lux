"""The render seam captures leaf geometry, and skips containers.

``record_leaf_geometry`` is called by the render seam right after a factory-backed
element paints. A container is skipped — a window-like one records its own window
rect and a pure container has no single widget rect — so it records nothing. The
leaf path reads ImGui's last item and is verified at the demo gate; the container
skip needs no ImGui call, so it is checked headless here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.window import WindowElement

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory


def test_a_window_records_no_leaf_geometry(
    real_imgui_factory: ImGuiRendererFactory,
) -> None:
    real_imgui_factory.record_leaf_geometry(WindowElement(id="w1"))
    real_imgui_factory.geometry.complete()
    assert real_imgui_factory.geometry.recorder.snapshot().element_for("", "w1") is None


def test_a_pure_container_records_no_leaf_geometry(
    real_imgui_factory: ImGuiRendererFactory,
) -> None:
    real_imgui_factory.record_leaf_geometry(GroupElement(id="g1"))
    real_imgui_factory.geometry.complete()
    assert real_imgui_factory.geometry.recorder.snapshot().element_for("", "g1") is None
