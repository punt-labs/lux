"""Migration gate for the ABC ``separator`` leaf — Levels 1-5 + self-validation.

A display-only leaf: a divider with an optional ``tooltip``, no children and no
interaction (Level 4 is N/A). Separator is the one anonymous-capable kind — it
may arrive with an empty id, which the wire omits and the dual-write pump
re-stamps through the ``Anonymizable`` capability. Levels 3 and 5 drive the real
Hub/Display boundary — the pickle scene wire and the ``DisplayServer``
receive/rebind path — never a stub.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.anonymizable import Anonymizable
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import GroupElement, SeparatorElement
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
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    return sock


def _inspect(server: DisplayServer, *elements: Element) -> QueryResponse:
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


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_named_separator_roundtrips_to_abc(self) -> None:
        restored = _decode(SeparatorElement(id="s1").to_dict())
        assert isinstance(restored, SeparatorElement)
        assert restored.id == "s1"

    def test_wire_shape_matches_legacy_bytes(self) -> None:
        assert SeparatorElement(id="s1").to_dict() == {"kind": "separator", "id": "s1"}

    def test_anonymous_separator_omits_id_on_the_wire(self) -> None:
        assert SeparatorElement().to_dict() == {"kind": "separator"}
        restored = _decode(SeparatorElement().to_dict())
        assert isinstance(restored, SeparatorElement)
        assert restored.id == ""

    def test_tooltip_round_trips_through_abc_path(self) -> None:
        """A separator tooltip survives encode → decode (the codec owns it)."""
        wire = SeparatorElement(id="s1", tooltip="section break").to_dict()
        assert wire["tooltip"] == "section break"
        restored = _decode(wire)
        assert isinstance(restored, SeparatorElement)
        assert restored.tooltip == "section break"


# -- self-validation (DES-039) ----------------------------------------------


class TestSelfValidation:
    def test_separator_validates_vacuously(self) -> None:
        """A divider has no invalid state — the ABC default returns ()."""
        assert SeparatorElement(id="s1").validate() == ()

    def test_non_string_id_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"separator element.*'id'"):
            SeparatorElement.from_dict({"kind": "separator", "id": 99})

    def test_valid_separator_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([SeparatorElement(id="s1")]).ok


# -- the anonymous-id capability --------------------------------------------


class TestAnonymizable:
    def test_separator_is_anonymizable(self) -> None:
        assert isinstance(SeparatorElement(), Anonymizable)

    def test_with_synthesized_id_returns_a_restamped_copy(self) -> None:
        anon = SeparatorElement(tooltip="hr")
        stamped = anon.with_synthesized_id("separator:2")
        # The copy carries the new id and preserves the tooltip.
        assert stamped.id == "separator:2"
        assert stamped.tooltip == "hr"
        # The original is untouched so the wire/renderer view keeps its empty id.
        assert anon.id == ""
        assert stamped is not anon


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_separator_crosses_as_pickled_entry(self) -> None:
        separator = SeparatorElement(id="s1", tooltip="break")
        wire = message_to_dict(
            SceneMessage(id="s1", elements=[separator], frame_id="s1")
        )
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC separator must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, SeparatorElement)
        assert r.id == "s1"
        assert r.tooltip == "break"


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_separator_renderer_factory(self) -> None:
        scene = SceneMessage(
            id="s1", elements=[SeparatorElement(id="s1")], frame_id="s1"
        )
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        separator = received.elements[0]
        assert isinstance(separator, SeparatorElement)

        before = separator._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert separator._renderer_factory is factory


# -- ABC decode nesting -----------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_separator_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "separator", "id": "s1"}],
        }
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], SeparatorElement)


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_separator_is_recorded(self) -> None:
        resp = _inspect(_server(), SeparatorElement(id="s1"))
        assert _record(resp, "s1")["kind"] == "separator"

    def test_separator_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), SeparatorElement(id="s1"))
        props = _record(resp, "s1")["props"]
        assert isinstance(props, dict)
        assert props == {"tooltip": None}


# -- patch path -------------------------------------------------------------


class TestPatchPath:
    def test_apply_patch_sets_tooltip_in_place(self) -> None:
        separator = SeparatorElement(id="s1")
        returned = separator.apply_patch({"tooltip": "break"})
        assert returned is separator
        assert separator.tooltip == "break"

    def test_apply_patch_rejects_non_string_tooltip(self) -> None:
        separator = SeparatorElement(id="s1")
        with pytest.raises(TypeError, match="tooltip"):
            separator.apply_patch({"tooltip": 42})


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_separator_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(SeparatorElement(id="s1"))
        assert encoded == {"kind": "separator", "id": "s1"}
