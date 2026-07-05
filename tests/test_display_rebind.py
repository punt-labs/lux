"""Display receive→rebind path — the C1/C2 renderer-factory rebind.

Drives the real production wiring: build ABC elements, ship them through the
native-pickle scene wire (``protocol/messages/scene.py``), and feed the
received copies through ``DisplayServer._wrap_abc_elements``. Off the wire
every element carries the fail-loud ``RaisingRendererFactory`` sentinel;
after the rebind every element — and every child of a composite — carries the
Display's real ``ImGuiRendererFactory`` so ``render()`` resolves a real
renderer instead of raising. No stub factory: the DisplayServer constructs its
own production ``ImGuiRendererFactory``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    DialogElement,
    TextElement,
)
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory


def _received_scene(msg: SceneMessage) -> SceneMessage:
    """Return ``msg`` after a real native-pickle wire roundtrip."""
    wire = message_to_dict(msg)
    for entry in wire["elements"]:
        assert "_pickled" in entry, "ABC element must cross as a pickled wire entry"
    restored = message_from_dict(wire)
    assert isinstance(restored, SceneMessage)
    return restored


def _abc_elements(msg: SceneMessage) -> list[AbcElement]:
    """Return the received top-level elements narrowed to the Element ABC."""
    narrowed: list[AbcElement] = []
    for elem in msg.elements:
        assert isinstance(elem, AbcElement)
        narrowed.append(elem)
    return narrowed


def _server() -> DisplayServer:
    """Construct an in-process DisplayServer (no socket bound) on a temp path."""
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


def test_received_elements_carry_raising_sentinel_before_rebind() -> None:
    """Off the wire, every ABC element carries the fail-loud sentinel factory."""
    received = _received_scene(
        SceneMessage(
            id="s1",
            elements=[
                TextElement(id="t1", content="hi"),
                ButtonElement(id="b1", label="OK"),
            ],
        )
    )
    for elem in _abc_elements(received):
        assert isinstance(elem._renderer_factory, RaisingRendererFactory)


def test_wrap_abc_elements_rebinds_the_real_display_factory() -> None:
    """After ``_wrap_abc_elements`` every element carries the Display's factory."""
    server = _server()
    received = _received_scene(
        SceneMessage(
            id="s1",
            elements=[
                TextElement(id="t1", content="hi"),
                ButtonElement(id="b1", label="OK"),
            ],
        )
    )

    server._wrap_abc_elements(received)

    factory = server._imgui_renderer_factory
    assert isinstance(factory, ImGuiRendererFactory)
    for elem in _abc_elements(received):
        assert elem._renderer_factory is factory


def test_rebind_recurses_into_dialog_children() -> None:
    """A composite's children are rebound in the same walk (recursion proof)."""
    dialog = DialogElement(id="d1", title="Confirm")
    dialog.install_children((ButtonElement(id="ok", label="OK"),))
    received = _received_scene(SceneMessage(id="s1", elements=[dialog]))
    restored_dialog = received.elements[0]
    assert isinstance(restored_dialog, DialogElement)
    child = restored_dialog.children[0]

    # Pre-rebind: both the dialog and its child carry the sentinel. Read into
    # locals so the isinstance narrowing does not stick to the attribute across
    # the rebind below.
    dialog_factory = restored_dialog._renderer_factory
    child_factory = child._renderer_factory
    assert isinstance(dialog_factory, RaisingRendererFactory)
    assert isinstance(child_factory, RaisingRendererFactory)

    server = _server()
    server._wrap_abc_elements(received)

    factory = server._imgui_renderer_factory
    assert restored_dialog._renderer_factory is factory
    assert child._renderer_factory is factory
