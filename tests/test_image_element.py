"""Migration gate for the ABC ``image`` leaf — Levels 1-5 + self-validation.

A display-only leaf with the batch's one real type decision: the pixel source is
a discriminated ``PathImage`` xor ``DataImage`` (rule 5), so "neither" and "both"
are wire errors the constructor refuses. Textures upload display-side through the
TextureCache; the element carries only the serialized source. Levels 3 and 5
drive the real Hub/Display boundary — never a stub.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from punt_lux.display.render_loop import RenderLoop
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import GroupElement, ImageElement
from punt_lux.protocol.elements.image_source import DataImage, PathImage
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> RenderLoop:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return RenderLoop(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_sock() -> Any:
    from unittest.mock import MagicMock

    sock = MagicMock()
    sock.fileno.return_value = 7
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    return sock


def _inspect(server: RenderLoop, *elements: Element) -> QueryResponse:
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=list(elements), frame_id="s1")
    )
    return server.query_router.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


# -- the discriminated source: exactly one of path / data -------------------


class TestDiscriminatedSource:
    def test_path_image_projects_path_and_no_data(self) -> None:
        elem = ImageElement(id="i1", path="/tmp/a.png")
        assert isinstance(elem.source, PathImage)
        assert (elem.path, elem.data) == ("/tmp/a.png", None)

    def test_data_image_projects_data_and_no_path(self) -> None:
        elem = ImageElement(id="i2", data="base64blob")
        assert isinstance(elem.source, DataImage)
        assert (elem.data, elem.path) == ("base64blob", None)

    def test_neither_path_nor_data_is_refused(self) -> None:
        with pytest.raises(ValueError, match="requires either"):
            ImageElement(id="i3")

    def test_both_path_and_data_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            ImageElement(id="i4", path="/a.png", data="blob")


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_path_image_roundtrips_to_abc(self) -> None:
        restored = _decode(ImageElement(id="i1", path="/tmp/a.png", width=10).to_dict())
        assert isinstance(restored, ImageElement)
        assert restored.path == "/tmp/a.png"
        assert restored.width == 10

    def test_data_image_roundtrips_to_abc(self) -> None:
        restored = _decode(ImageElement(id="i2", data="blob").to_dict())
        assert isinstance(restored, ImageElement)
        assert restored.data == "blob"

    def test_wire_shape_matches_legacy_bytes(self) -> None:
        assert ImageElement(id="i1", path="/tmp/x.png", width=100).to_dict() == {
            "kind": "image",
            "id": "i1",
            "path": "/tmp/x.png",
            "width": 100,
        }

    def test_all_fields_round_trip(self) -> None:
        wire = ImageElement(
            id="i1",
            path="/a.png",
            format="png",
            alt="a cat",
            width=64,
            height=48,
            tooltip="hover",
        ).to_dict()
        assert wire == {
            "kind": "image",
            "id": "i1",
            "path": "/a.png",
            "format": "png",
            "alt": "a cat",
            "width": 64,
            "height": 48,
            "tooltip": "hover",
        }
        restored = _decode(wire)
        assert isinstance(restored, ImageElement)
        assert restored.format == "png"
        assert restored.alt == "a cat"
        assert restored.tooltip == "hover"


# -- self-validation (DES-039) + boundary rejection -------------------------


class TestSelfValidation:
    def test_image_validates_vacuously(self) -> None:
        """The source invariant is established at construction — no invalid state."""
        assert ImageElement(id="i1", path="/a.png").validate() == ()

    def test_non_int_width_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"image element.*'width'"):
            ImageElement.from_dict(
                {"kind": "image", "id": "i1", "path": "/a.png", "width": "100"}
            )

    def test_non_string_path_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"image element.*'path'"):
            ImageElement.from_dict({"kind": "image", "id": "i1", "path": 7})

    def test_unknown_format_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"image element field 'format'"):
            ImageElement.from_dict(
                {"kind": "image", "id": "i1", "path": "/a.png", "format": "webp"}
            )

    def test_wire_with_neither_source_is_refused(self) -> None:
        with pytest.raises(ValueError, match="requires either"):
            ImageElement.from_dict({"kind": "image", "id": "i1"})

    def test_valid_image_passes_the_tree_walk(self) -> None:
        assert (
            ElementTreeValidator()
            .validate_tree([ImageElement(id="i1", path="/a.png")])
            .ok
        )


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_image_crosses_as_pickled_entry(self) -> None:
        image = ImageElement(id="i1", path="/a.png", alt="cat", tooltip="hover")
        wire = message_to_dict(SceneMessage(id="s1", elements=[image], frame_id="s1"))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC image must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, ImageElement)
        assert r.path == "/a.png"
        assert r.alt == "cat"
        assert r.tooltip == "hover"


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_image_renderer_factory(self) -> None:
        scene = SceneMessage(
            id="s1", elements=[ImageElement(id="i1", path="/a.png")], frame_id="s1"
        )
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        image = received.elements[0]
        assert isinstance(image, ImageElement)

        before = image._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert image._renderer_factory is factory


# -- ABC decode nesting -----------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_image_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "image", "id": "i1", "path": "/a.png"}],
        }
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], ImageElement)


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_image_is_recorded(self) -> None:
        resp = _inspect(_server(), ImageElement(id="i1", path="/a.png"))
        assert _record(resp, "i1")["kind"] == "image"

    def test_image_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), ImageElement(id="i1", path="/a.png"))
        props = _record(resp, "i1")["props"]
        assert isinstance(props, dict)
        assert props == {
            "path": "/a.png",
            "data": None,
            "format": None,
            "alt": None,
            "width": None,
            "height": None,
            "tooltip": None,
        }


# -- patch path -------------------------------------------------------------


class TestPatchPath:
    def test_apply_patch_advances_width_in_place(self) -> None:
        image = ImageElement(id="i1", path="/a.png")
        returned = image.apply_patch({"width": 128})
        assert returned is image
        assert image.width == 128

    def test_apply_patch_switches_source_to_data(self) -> None:
        image = ImageElement(id="i1", path="/a.png")
        image.apply_patch({"data": "blob"})
        assert isinstance(image.source, DataImage)
        assert (image.data, image.path) == ("blob", None)

    def test_apply_patch_switches_source_to_path(self) -> None:
        image = ImageElement(id="i1", data="blob")
        image.apply_patch({"path": "/b.png"})
        assert isinstance(image.source, PathImage)
        assert (image.path, image.data) == ("/b.png", None)

    def test_apply_patch_rejects_both_source_keys(self) -> None:
        image = ImageElement(id="i1", path="/a.png")
        with pytest.raises(ValueError, match="not both"):
            image.apply_patch({"path": "/b.png", "data": "blob"})

    def test_both_source_patch_leaves_element_unchanged(self) -> None:
        """The pair-check raises before any setter runs — nothing mutates."""
        image = ImageElement(id="i1", path="/a.png", width=10)
        with pytest.raises(ValueError, match="not both"):
            image.apply_patch({"path": "/b.png", "data": "blob", "width": 99})
        assert isinstance(image.source, PathImage)
        assert (image.path, image.data, image.width) == ("/a.png", None, 10)

    def test_apply_patch_rejects_unknown_format(self) -> None:
        image = ImageElement(id="i1", path="/a.png")
        with pytest.raises(ValueError, match="format"):
            image.apply_patch({"format": "webp"})


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_image_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(ImageElement(id="i1", path="/a.png"))
        assert encoded == {"kind": "image", "id": "i1", "path": "/a.png"}
