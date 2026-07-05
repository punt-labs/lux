"""Migration gate for the ABC ``progress`` leaf — Levels 1-5 + self-validation.

A display-only leaf: a fill ``fraction`` plus an optional overlay ``label``,
no children and no interaction (Level 4 is N/A). Levels 3 and 5 drive the real
Hub/Display boundary — the pickle scene wire and the ``DisplayServer``
receive/rebind path — never a stub. The fork-gate and tooltip cases guard the
two seams the reconciled design flagged: an all-ABC group must admit a progress
child, and the codec must own ``tooltip`` (the legacy dataclass dropped it).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import GroupElement, ProgressElement
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


# -- helpers ----------------------------------------------------------------


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_sock() -> MagicMock:
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


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_progress_roundtrips_to_abc(self) -> None:
        restored = _decode(
            ProgressElement(id="p1", fraction=0.5, label="Loading").to_dict()
        )
        assert isinstance(restored, ProgressElement)
        assert restored.fraction == 0.5
        assert restored.label == "Loading"

    def test_tooltip_round_trips_through_abc_path(self) -> None:
        """A progress tooltip survives encode → decode (the legacy codec dropped it)."""
        wire = ProgressElement(id="p1", fraction=0.5, tooltip="ETA 3s").to_dict()
        assert wire["tooltip"] == "ETA 3s"
        restored = _decode(wire)
        assert isinstance(restored, ProgressElement)
        assert restored.tooltip == "ETA 3s"

    def test_wire_shape_matches_legacy_bytes(self) -> None:
        assert ProgressElement(id="p1", fraction=0.5, label="Loading").to_dict() == {
            "kind": "progress",
            "id": "p1",
            "fraction": 0.5,
            "label": "Loading",
        }

    def test_defaults_omit_label_and_tooltip(self) -> None:
        assert ProgressElement(id="p1").to_dict() == {
            "kind": "progress",
            "id": "p1",
            "fraction": 0.0,
        }


# -- self-validation (DES-039) ----------------------------------------------


class TestSelfValidation:
    def test_valid_fraction_has_no_errors(self) -> None:
        assert ProgressElement(id="p1", fraction=0.5).validate() == ()

    @pytest.mark.parametrize("fraction", [0.0, 1.0])
    def test_boundary_fractions_are_valid(self, fraction: float) -> None:
        assert ProgressElement(id="p1", fraction=fraction).validate() == ()

    @pytest.mark.parametrize("fraction", [1.5, -0.5, float("nan")])
    def test_out_of_range_fraction_reports_one_error(self, fraction: float) -> None:
        errors = ProgressElement(id="p1", fraction=fraction).validate()
        assert len(errors) == 1
        assert errors[0].element_id == "p1"
        assert errors[0].element_kind == "progress"
        assert "fraction must be in [0, 1]" in errors[0].message

    def test_non_number_fraction_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match="fraction"):
            ProgressElement.from_dict({"kind": "progress", "id": "p1", "fraction": "x"})

    def test_bool_fraction_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match="fraction"):
            ProgressElement.from_dict(
                {"kind": "progress", "id": "p1", "fraction": True}
            )

    def test_valid_progress_passes_the_tree_walk(self) -> None:
        assert (
            ElementTreeValidator()
            .validate_tree([ProgressElement(id="p1", fraction=0.5)])
            .ok
        )


class TestShowRejectsInvalidProgress:
    @patch(_CLIENT_GET)
    def test_show_rejects_out_of_range_progress(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "progress", "id": "p1", "fraction": 2.0}])
        assert result.startswith("error: scene not rendered")
        assert "[progress 'p1']" in result
        assert "fraction must be in [0, 1]" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_progress_nested_in_group(self, mock_get: MagicMock) -> None:
        """A bad progress nested in an all-ABC group is collected by the walk."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "group",
                    "id": "g1",
                    "children": [
                        {"kind": "text", "id": "ok", "content": "fine"},
                        {"kind": "progress", "id": "bad", "fraction": -0.5},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[progress 'bad']" in result
        client.show.assert_not_called()


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_progress_crosses_as_pickled_entry(self) -> None:
        progress = ProgressElement(
            id="p1", fraction=0.5, label="Loading", tooltip="ETA"
        )
        wire = message_to_dict(SceneMessage(id="s1", elements=[progress]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC progress must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, ProgressElement)
        assert r.fraction == 0.5
        assert r.label == "Loading"
        assert r.tooltip == "ETA"


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_progress_renderer_factory(self) -> None:
        scene = SceneMessage(id="s1", elements=[ProgressElement(id="p1", fraction=0.5)])
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        progress = received.elements[0]
        assert isinstance(progress, ProgressElement)

        # Read into a local so the isinstance narrowing does not stick to the
        # attribute across the rebind below.
        before = progress._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert progress._renderer_factory is factory


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_progress_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "progress", "id": "p1", "fraction": 0.5}],
        }
        assert JsonGroupDecoder.is_all_abc(wire)
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], ProgressElement)

    def test_group_and_progress_child_report_abc_render_path(self) -> None:
        group = GroupElement(
            id="g1", children=(ProgressElement(id="p1", fraction=0.5),)
        )
        resp = _inspect(_server(), group)
        assert _record(resp, "g1")["render_path"] == "abc"
        assert _record(resp, "p1")["render_path"] == "abc"


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_progress_reports_abc_render_path(self) -> None:
        resp = _inspect(_server(), ProgressElement(id="p1", fraction=0.42))
        assert _record(resp, "p1")["render_path"] == "abc"

    def test_progress_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), ProgressElement(id="p1", fraction=0.42))
        props = _record(resp, "p1")["props"]
        assert isinstance(props, dict)
        assert props == {"fraction": 0.42, "label": "", "tooltip": None}


class TestPatchPath:
    def test_apply_patch_advances_fraction_in_place(self) -> None:
        """The patch flows through ``_set_fraction`` — not ``dataclasses.replace``."""
        progress = ProgressElement(id="p1", fraction=0.25)
        returned = progress.apply_patch({"fraction": 0.75})
        assert returned is progress
        assert progress.fraction == 0.75

    def test_apply_patch_rejects_non_number_fraction(self) -> None:
        progress = ProgressElement(id="p1", fraction=0.25)
        with pytest.raises(TypeError, match="fraction"):
            progress.apply_patch({"fraction": "fast"})

    @pytest.mark.parametrize("fraction", [1.5, -0.5, float("nan")])
    def test_apply_patch_rejects_out_of_range_fraction(self, fraction: float) -> None:
        """The patch path enforces the same [0, 1]+NaN gate as ``show``.

        A NaN or out-of-range patch is rejected and installs nothing — the
        prior fraction survives, so the render loop never computes
        ``int(nan)`` or paints a clamped 150%.
        """
        progress = ProgressElement(id="p1", fraction=0.25)
        with pytest.raises(ValueError, match=r"fraction must be in \[0, 1\]"):
            progress.apply_patch({"fraction": fraction})
        assert progress.fraction == 0.25

    def test_apply_patch_sets_label_and_tooltip(self) -> None:
        progress = ProgressElement(id="p1", fraction=0.5)
        progress.apply_patch({"label": "Done", "tooltip": "complete"})
        assert progress.label == "Done"
        assert progress.tooltip == "complete"


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_progress_without_raising(self) -> None:
        """A dedicated encode-path guard so the progress branch cannot evaporate."""
        encoded = JsonEncoderFactory().encode(ProgressElement(id="p1", fraction=0.5))
        assert encoded == {"kind": "progress", "id": "p1", "fraction": 0.5}
