"""Migration gate for the ABC ``markdown`` leaf — Levels 1-5 + self-validation.

A display-only leaf: a block of markdown ``content`` with an optional
``tooltip``, no children and no interaction (Level 4 is N/A). Levels 3 and 5
drive the real Hub/Display boundary — the pickle scene wire and the
``DisplayServer`` receive/rebind path — never a stub. The tooltip case guards
the seam the reconciled design flagged: the codec must own ``tooltip`` (the
legacy dataclass dropped it onto a generic path ABC kinds never reach).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import GroupElement, MarkdownElement
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder
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


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_sock() -> Any:
    from unittest.mock import MagicMock

    sock = MagicMock()
    sock.fileno.return_value = 7
    return sock


def _inspect(server: DisplayServer, *elements: Element) -> QueryResponse:
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=list(elements), frame_id="s1")
    )
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_markdown_roundtrips_to_abc(self) -> None:
        restored = _decode(MarkdownElement(id="md1", content="# Hi").to_dict())
        assert isinstance(restored, MarkdownElement)
        assert restored.content == "# Hi"

    def test_tooltip_round_trips_through_abc_path(self) -> None:
        """A markdown tooltip survives encode → decode (the legacy codec dropped it)."""
        wire = MarkdownElement(id="md1", content="x", tooltip="notes").to_dict()
        assert wire["tooltip"] == "notes"
        restored = _decode(wire)
        assert isinstance(restored, MarkdownElement)
        assert restored.tooltip == "notes"

    def test_wire_shape_matches_legacy_bytes(self) -> None:
        assert MarkdownElement(id="md1", content="# Hi").to_dict() == {
            "kind": "markdown",
            "id": "md1",
            "content": "# Hi",
        }


# -- self-validation (DES-039) ----------------------------------------------


class TestSelfValidation:
    def test_markdown_has_no_errors(self) -> None:
        assert MarkdownElement(id="md1", content="# Hi").validate() == ()

    def test_non_string_content_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"markdown element.*'content'"):
            MarkdownElement.from_dict({"kind": "markdown", "id": "md1", "content": 42})

    def test_missing_content_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"markdown element.*'content'"):
            MarkdownElement.from_dict({"kind": "markdown", "id": "md1"})

    def test_valid_markdown_passes_the_tree_walk(self) -> None:
        assert (
            ElementTreeValidator()
            .validate_tree([MarkdownElement(id="md1", content="# Hi")])
            .ok
        )


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_markdown_crosses_as_pickled_entry(self) -> None:
        markdown = MarkdownElement(id="md1", content="# Hi", tooltip="notes")
        wire = message_to_dict(
            SceneMessage(id="s1", elements=[markdown], frame_id="s1")
        )
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC markdown must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, MarkdownElement)
        assert r.content == "# Hi"
        assert r.tooltip == "notes"


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_markdown_renderer_factory(self) -> None:
        scene = SceneMessage(
            id="s1", elements=[MarkdownElement(id="md1", content="# Hi")], frame_id="s1"
        )
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        markdown = received.elements[0]
        assert isinstance(markdown, MarkdownElement)

        before = markdown._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert markdown._renderer_factory is factory


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_markdown_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "markdown", "id": "md1", "content": "# Hi"}],
        }
        assert JsonGroupDecoder.is_all_abc(wire)
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], MarkdownElement)


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_markdown_reports_abc_render_path(self) -> None:
        resp = _inspect(_server(), MarkdownElement(id="md1", content="# Hi"))
        assert _record(resp, "md1")["render_path"] == "abc"

    def test_markdown_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), MarkdownElement(id="md1", content="# Hi"))
        props = _record(resp, "md1")["props"]
        assert isinstance(props, dict)
        assert props == {"content": "# Hi", "tooltip": None}


# -- patch path -------------------------------------------------------------


class TestPatchPath:
    def test_apply_patch_advances_content_in_place(self) -> None:
        markdown = MarkdownElement(id="md1", content="# One")
        returned = markdown.apply_patch({"content": "# Two"})
        assert returned is markdown
        assert markdown.content == "# Two"

    def test_apply_patch_rejects_non_string_content(self) -> None:
        markdown = MarkdownElement(id="md1", content="# One")
        with pytest.raises(TypeError, match="content"):
            markdown.apply_patch({"content": 42})

    def test_apply_patch_sets_tooltip(self) -> None:
        markdown = MarkdownElement(id="md1", content="# One")
        markdown.apply_patch({"tooltip": "notes"})
        assert markdown.tooltip == "notes"


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_markdown_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(MarkdownElement(id="md1", content="# Hi"))
        assert encoded == {"kind": "markdown", "id": "md1", "content": "# Hi"}
