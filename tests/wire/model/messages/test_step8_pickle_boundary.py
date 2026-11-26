"""Public operation/menu values do not become Hub-to-Display pickle globals."""

from __future__ import annotations

import pickle

import pytest

from punt_lux.hub.hub_factory import hub_element_factory
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.model.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.wire.model.messages.pickled_element_codec import PickledElementCodec
from punt_lux.wire.model.messages.scene_codec import SceneCodec
from punt_lux.wire.model.scene_presentation import ScenePresentation
from punt_lux.wire.operations import FrameSpec, RenderRequest
from tests.root_module_moves import MOVED_MODULES

_REQUIRED: dict[str, dict[str, object]] = {
    "image": {"path": "x.png"},
    "markdown": {"content": "m"},
    "progress": {"fraction": 0.5},
    "terminal": {"session": "s1"},
    "text": {"content": "t"},
}
_MOVED = (
    b"punt_lux.wire.operations",
    b"punt_lux.wire.model.session_callback",
    b"punt_lux.wire.model.menu_models",
    b"punt_lux.wire.model.menu_action",
    b"punt_lux.wire.model.connection_scoped_id",
    b"punt_lux.wire.model.frame_ownership",
    b"punt_lux.wire.model.scene_presentation",
    *(name.encode() for name in (*MOVED_MODULES, *MOVED_MODULES.values())),
)


@pytest.mark.parametrize("kind", sorted(DEFAULT_ABC_REGISTRY.all_kinds))
def test_every_shipped_kind_retains_its_pickle_globals(kind: str) -> None:
    raw: dict[str, object] = {"kind": kind, "id": "element", **_REQUIRED.get(kind, {})}
    if kind == "button":
        raw["handlers"] = [{"event": "click", "publish": ["clicked"]}]
    element = hub_element_factory(ConnectionId("pickle-owner")).element_from_dict(raw)
    payload = pickle.dumps(element)
    assert not any(prefix in payload for prefix in _MOVED)
    if kind == "button":
        assert b"punt_lux.hub.hub_factory" in payload
        assert b"HubPublishSink" in payload
    codec = PickledElementCodec()
    assert (
        codec.decode_all(codec.encode_all([element]))[0].to_dict() == element.to_dict()
    )


def test_presentation_request_values_become_primitive_wire_fields() -> None:
    request = RenderRequest(
        scene_id="scene",
        elements=[],
        frame=FrameSpec(frame_id="frame", size=(400, 300)),
    )
    presentation = request.presentation()
    assert isinstance(presentation, ScenePresentation)
    message = presentation.message("scene", [])
    wire = SceneCodec.encode(message)
    assert wire["frame_id"] == "frame"
    assert wire["frame_size"] == [400, 300]
    assert wire["elements"] == []
    assert SceneCodec.decode(wire) == message
