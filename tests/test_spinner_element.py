"""Migration gate for the ABC ``spinner`` leaf — Levels 1-5 + self-validation.

A display-only leaf: an animated spinner with ``label``/``radius``/``color``
and an optional ``tooltip``, no children and no interaction (Level 4 is N/A).
Levels 3 and 5 drive the real Hub/Display boundary — the pickle scene wire and
the ``DisplayServer`` receive/rebind path — never a stub. The tooltip case
guards the seam the reconciled design flagged: the codec must own ``tooltip``
(the legacy dataclass dropped it onto a generic path ABC kinds never reach).
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
from punt_lux.protocol.elements import GroupElement, SpinnerElement
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
    server._handle_message(_mock_sock(), SceneMessage(id="s1", elements=list(elements)))
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_spinner_roundtrips_to_abc(self) -> None:
        restored = _decode(SpinnerElement(id="sp1", label="Loading").to_dict())
        assert isinstance(restored, SpinnerElement)
        assert restored.label == "Loading"

    def test_tooltip_round_trips_through_abc_path(self) -> None:
        """A spinner tooltip survives encode → decode (the legacy codec dropped it)."""
        wire = SpinnerElement(id="sp1", tooltip="working").to_dict()
        assert wire["tooltip"] == "working"
        restored = _decode(wire)
        assert isinstance(restored, SpinnerElement)
        assert restored.tooltip == "working"

    def test_wire_shape_matches_legacy_bytes(self) -> None:
        assert SpinnerElement(id="sp1").to_dict() == {
            "kind": "spinner",
            "id": "sp1",
            "radius": 16.0,
            "color": "#3399FF",
        }

    def test_non_default_fields_round_trip(self) -> None:
        wire = SpinnerElement(
            id="sp1", label="Busy", radius=24.0, color="#FF0000"
        ).to_dict()
        assert wire == {
            "kind": "spinner",
            "id": "sp1",
            "radius": 24.0,
            "color": "#FF0000",
            "label": "Busy",
        }
        restored = _decode(wire)
        assert isinstance(restored, SpinnerElement)
        assert (restored.radius, restored.color, restored.label) == (
            24.0,
            "#FF0000",
            "Busy",
        )


# -- self-validation (DES-039) ----------------------------------------------


class TestSelfValidation:
    def test_default_spinner_validates_clean(self) -> None:
        """The default radius (16.0) is positive, so validate() returns ()."""
        assert SpinnerElement(id="sp1").validate() == ()

    def test_zero_radius_is_flagged(self) -> None:
        """A zero radius paints a zero-size arc that vanishes — validate() flags it."""
        errors = SpinnerElement(id="sp1", radius=0.0).validate()
        assert len(errors) == 1
        assert errors[0].element_id == "sp1"

    def test_negative_radius_is_flagged(self) -> None:
        assert SpinnerElement(id="sp1", radius=-4.0).validate() != ()

    def test_non_numeric_radius_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
            SpinnerElement.from_dict({"kind": "spinner", "id": "sp1", "radius": "big"})

    def test_missing_id_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'id'"):
            SpinnerElement.from_dict({"kind": "spinner"})

    def test_valid_spinner_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([SpinnerElement(id="sp1")]).ok

    def test_zero_radius_fails_the_tree_walk(self) -> None:
        result = ElementTreeValidator().validate_tree(
            [SpinnerElement(id="sp1", radius=0.0)]
        )
        assert not result.ok

    def test_nan_radius_fails_the_tree_walk(self) -> None:
        """A NaN radius is unpaintable — validate() flags it and the walk fails."""
        result = ElementTreeValidator().validate_tree(
            [SpinnerElement(id="sp1", radius=float("nan"))]
        )
        assert not result.ok


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_spinner_crosses_as_pickled_entry(self) -> None:
        spinner = SpinnerElement(id="sp1", label="Load", tooltip="working")
        wire = message_to_dict(SceneMessage(id="s1", elements=[spinner]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC spinner must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, SpinnerElement)
        assert r.label == "Load"
        assert r.tooltip == "working"


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_spinner_renderer_factory(self) -> None:
        scene = SceneMessage(id="s1", elements=[SpinnerElement(id="sp1")])
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        spinner = received.elements[0]
        assert isinstance(spinner, SpinnerElement)

        before = spinner._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert spinner._renderer_factory is factory


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_spinner_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "spinner", "id": "sp1"}],
        }
        assert JsonGroupDecoder.is_all_abc(wire)
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], SpinnerElement)


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_spinner_reports_abc_render_path(self) -> None:
        resp = _inspect(_server(), SpinnerElement(id="sp1"))
        assert _record(resp, "sp1")["render_path"] == "abc"

    def test_spinner_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), SpinnerElement(id="sp1"))
        props = _record(resp, "sp1")["props"]
        assert isinstance(props, dict)
        assert props == {
            "label": "",
            "radius": 16.0,
            "color": "#3399FF",
            "tooltip": None,
        }


# -- patch path -------------------------------------------------------------


class TestPatchPath:
    def test_apply_patch_advances_radius_in_place(self) -> None:
        spinner = SpinnerElement(id="sp1")
        returned = spinner.apply_patch({"radius": 24.0})
        assert returned is spinner
        assert spinner.radius == 24.0

    def test_apply_patch_rejects_non_positive_radius(self) -> None:
        spinner = SpinnerElement(id="sp1")
        with pytest.raises(ValueError, match="radius must be positive"):
            spinner.apply_patch({"radius": 0.0})

    def test_apply_patch_rejects_nan_radius(self) -> None:
        spinner = SpinnerElement(id="sp1")
        with pytest.raises(ValueError, match="radius must be positive"):
            spinner.apply_patch({"radius": float("nan")})

    def test_apply_patch_advances_label_and_color(self) -> None:
        spinner = SpinnerElement(id="sp1")
        spinner.apply_patch({"label": "Busy", "color": "#00FF00"})
        assert (spinner.label, spinner.color) == ("Busy", "#00FF00")

    def test_apply_patch_rejects_non_numeric_radius(self) -> None:
        spinner = SpinnerElement(id="sp1")
        with pytest.raises(TypeError, match="radius"):
            spinner.apply_patch({"radius": "big"})

    def test_apply_patch_sets_tooltip(self) -> None:
        spinner = SpinnerElement(id="sp1")
        spinner.apply_patch({"tooltip": "working"})
        assert spinner.tooltip == "working"


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_spinner_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(SpinnerElement(id="sp1"))
        assert encoded == {
            "kind": "spinner",
            "id": "sp1",
            "radius": 16.0,
            "color": "#3399FF",
        }
