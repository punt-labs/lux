"""The scene and client routes over the real facade through TestClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.operations import RenderTableRequest
from punt_lux.operations.display_reply import DisplayReplied
from punt_lux.protocol.compositions import TableComposition, TableCompositionSpec

from ._fakes import StubPort, make_client

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from httpx import Response

_TEXT = {"kind": "text", "id": "t1", "content": "hi"}
_TABLE_BODY = {
    "scene_id": "issues",
    "columns": ["ID", "Status"],
    "rows": [["1", "open"]],
    "filters": [{"type": "search", "column": [0]}],
}


def _render(client: TestClient, scene_id: str = "s1") -> Response:
    return cast(
        "Response",
        client.put(
            f"/scenes/{scene_id}",
            json={"scene_id": scene_id, "elements": [_TEXT]},
        ),
    )


def test_render_installs_a_scene() -> None:
    client = make_client()
    resp = _render(client)
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok", "scene_id": "s1"}


def test_render_rejects_a_body_scene_id_that_differs_from_the_path() -> None:
    # The path names the scene and is authoritative; a body naming a different
    # scene is a contradiction the route rejects rather than letting the body win.
    client = make_client()
    resp = client.put(
        "/scenes/path-id",
        json={"scene_id": "body-id", "elements": [_TEXT]},
    )
    assert resp.status_code == 422
    assert "path-id" in resp.json()["detail"]
    assert "body-id" in resp.json()["detail"]


def test_render_rejects_a_bad_layout_with_422() -> None:
    # FastAPI's own body-binding rejects the bad Literal before the operation
    # runs; the detail names the offending field.
    client = make_client()
    resp = client.put(
        "/scenes/s1",
        json={"scene_id": "s1", "elements": [], "layout": "diagonal"},
    )
    assert resp.status_code == 422
    assert any(part == "layout" for part in resp.json()["detail"][0]["loc"])


def test_render_rejects_a_duplicate_id_with_409() -> None:
    client = make_client()
    resp = client.put(
        "/scenes/s1",
        json={
            "scene_id": "s1",
            "elements": [
                {"kind": "text", "id": "dup", "content": "a"},
                {"kind": "text", "id": "dup", "content": "b"},
            ],
        },
    )
    assert resp.status_code == 409
    assert "duplicate" in resp.json()["detail"]


def test_update_applies_a_patch() -> None:
    client = make_client()
    client.put(
        "/scenes/s1",
        json={
            "scene_id": "s1",
            "elements": [
                {"kind": "collapsing_header", "id": "hdr", "label": "D", "open": False}
            ],
        },
    )
    resp = client.patch(
        "/scenes/s1", json={"patches": [{"id": "hdr", "set": {"open": True}}]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok", "scene_id": "s1"}


def test_update_of_an_unknown_element_is_409() -> None:
    client = make_client()
    _render(client)
    resp = client.patch(
        "/scenes/s1", json={"patches": [{"id": "ghost", "set": {"content": "x"}}]}
    )
    assert resp.status_code == 409
    assert "ghost" in resp.json()["detail"]


def test_clear_returns_ok() -> None:
    client = make_client()
    _render(client)
    resp = client.delete("/scenes")
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok"}


def test_scene_scoped_delete_removes_only_the_named_scene() -> None:
    client = make_client()
    _render(client, "alpha")
    _render(client, "beta")
    resp = client.delete("/scenes/alpha")
    assert resp.status_code == 200
    assert [s["scene_id"] for s in client.get("/scenes").json()["scenes"]] == ["beta"]


def test_list_scenes_reflects_a_rendered_scene() -> None:
    client = make_client()
    _render(client, "alpha")
    body = client.get("/scenes").json()
    assert [s["scene_id"] for s in body["scenes"]] == ["alpha"]
    assert body["scenes"][0]["owners"] == ["rest-test"]


def test_render_without_a_frame_lands_framed_by_its_scene_id() -> None:
    # THE RULE inherited at the REST PUT surface: a body that names no frame still
    # installs a framed scene, visible as a frame named by the scene id.
    client = make_client()
    resp = client.put("/scenes/alpha", json={"scene_id": "alpha", "elements": [_TEXT]})
    assert resp.status_code == 200
    body = client.get("/scenes").json()
    assert body["scenes"][0]["frame_id"] == "alpha"
    assert [f["frame_id"] for f in body["frames"]] == ["alpha"]


def test_inspect_scene_returns_the_tree() -> None:
    client = make_client()
    _render(client)
    body = client.get("/scenes/s1").json()
    assert body["scene_id"] == "s1"
    assert body["elements"][0]["id"] == "t1"
    assert body["elements"][0]["render_path"] in ("abc", "legacy")


def test_inspect_scene_want_mirror_binds_and_runs_the_mirror_branch() -> None:
    # The want_mirror query param binds at the REST tier and drives the proxied
    # mirror check: the StubPort's per-element reply resolves to a present mirror.
    mirror_reply = DisplayReplied(
        {
            "scene_id": "s1",
            "element_paths": [{"id": "t1", "domain_mirror_present": True}],
        }
    )
    client = make_client(display_port=StubPort(mirror_reply))
    _render(client)
    body = client.get("/scenes/s1", params={"want_mirror": "true"}).json()
    assert body["mirror"] == {"kind": "present", "present": True}


def test_inspect_scene_want_geometry_binds_and_carries_the_painted_rects() -> None:
    # The want_geometry query param binds at the REST tier and drives the proxied
    # geometry read: the StubPort's block resolves to a present geometry with the
    # element's painted rect and the frame rect.
    geometry_reply = DisplayReplied(
        {
            "scene_id": "s1",
            "geometry": {
                "elements": {
                    "t1": {
                        "rect": {"x": 8.0, "y": 8.0, "width": 120.0, "height": 18.0},
                        "paint_sequence": 0,
                        "stack_index": 2,
                    }
                },
                "anonymous": {
                    "separator:1": {
                        "rect": {"x": 0.0, "y": 30.0, "width": 100.0, "height": 1.0},
                        "paint_sequence": 1,
                        "stack_index": 2,
                    }
                },
                "frame": {
                    "rect": {"x": 0.0, "y": 0.0, "width": 640.0, "height": 480.0},
                    "stack_index": 0,
                },
            },
        }
    )
    client = make_client(display_port=StubPort(geometry_reply))
    _render(client)
    body = client.get("/scenes/s1", params={"want_geometry": "true"}).json()
    assert body["geometry"]["kind"] == "present"
    assert body["geometry"]["elements"]["t1"] == {
        "rect": {"x": 8.0, "y": 8.0, "width": 120.0, "height": 18.0},
        "paint_sequence": 0,
        "stack_index": 2,
    }
    # The anonymous map crosses REST too, under its per-frame kind:sequence key.
    assert body["geometry"]["anonymous"]["separator:1"] == {
        "rect": {"x": 0.0, "y": 30.0, "width": 100.0, "height": 1.0},
        "paint_sequence": 1,
        "stack_index": 2,
    }
    assert body["geometry"]["frame"] == {
        "rect": {"x": 0.0, "y": 0.0, "width": 640.0, "height": 480.0},
        "stack_index": 0,
    }


def test_inspect_unknown_scene_is_404() -> None:
    client = make_client()
    assert client.get("/scenes/ghost").status_code == 404


def test_list_clients_is_empty_without_sessions() -> None:
    client = make_client()
    resp = client.get("/clients")
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok", "clients": []}


def test_a_non_owning_rest_call_creates_no_phantom_client() -> None:
    # Removing the pub-sub routes removed the only path that called ensure_writer
    # for the REST scope, so a REST call that owns no scene must not surface as a
    # Hub session. (A render legitimately makes the scope a scene owner; a bare
    # read must not.) list_clients stays empty after non-owning calls.
    client = make_client()
    client.get("/menus")
    client.get("/scenes")
    assert client.get("/clients").json()["clients"] == []


def test_render_table_route_installs_the_live_composition() -> None:
    # The MCP surface's show_table works because render_table CONSTRUCTS the
    # composition (its filter handlers + FilteredTableModel) server-side. REST now
    # offers the same, so a REST-pushed composed table has live chrome.
    store = HubDisplay()
    client = make_client(store=store)
    resp = client.put("/scenes/issues/table", json=_TABLE_BODY)
    assert resp.status_code == 200
    search = cast(
        "AbcElement", store.resolve(SceneId("issues"), ElementId("table-search"))
    )
    # the search input carries the composition's SearchFilterHandler on top of its
    # built-in value mirror — two ValueChanged handlers, live chrome.
    assert search.handler_count(ValueChanged) == 2


def test_replacing_a_composed_scene_does_not_leak_the_old_model() -> None:
    # The poller re-pushes every ~3s, replacing the scene each time. Each push
    # builds fresh elements + FilteredTableModel + observers; the old ones — a
    # table<->model observer CYCLE — must die with the replace, not accumulate.
    import gc
    import weakref

    store = HubDisplay()
    client = make_client(store=store)
    client.put("/scenes/issues/table", json=_TABLE_BODY)
    old_table = store.resolve(SceneId("issues"), ElementId("table"))
    ref = weakref.ref(old_table)
    del old_table
    client.put("/scenes/issues/table", json=_TABLE_BODY)  # replace with fresh build
    gc.collect()
    assert ref() is None, "the replaced table (and its observer cycle) leaked"


def test_beads_board_request_installs_live_chrome_through_the_table_route() -> None:
    # `lux show beads` builds a RenderTableRequest; through the /table route the
    # Hub CONSTRUCTS the composition, so the beads board's search box, status/type
    # combos, and detail are live — the fix for the dead-chrome defect where the
    # generic render route decoded a pre-composed tree with built-in handlers only.
    from punt_lux.apps.beads_board import BeadsBoard

    issues = [
        {
            "id": "b-1",
            "title": "one",
            "status": "open",
            "priority": 1,
            "issue_type": "bug",
            "description": "d",
            "owner": "a",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
        }
    ]
    request = BeadsBoard("beads-cli-proj", "Beads: proj").request((issues, None))
    assert isinstance(request, RenderTableRequest)  # issues yield a table, not text
    store = HubDisplay()
    client = make_client(store=store)
    resp = client.put("/scenes/beads-cli-proj/table", json=request.model_dump())
    assert resp.status_code == 200
    scene = SceneId("beads-cli-proj")
    # The composed chrome is present as real elements, not a lone dead table.
    for element_id in ("table-search", "table", "table-detail"):
        assert store.resolve(scene, ElementId(element_id)) is not None
    search = cast("AbcElement", store.resolve(scene, ElementId("table-search")))
    # The search input carries the composition's live SearchFilterHandler on top
    # of its built-in value mirror — two ValueChanged handlers, live chrome.
    assert search.handler_count(ValueChanged) == 2


def test_render_table_route_rejects_a_body_scene_id_that_differs() -> None:
    client = make_client()
    resp = client.put("/scenes/path-id/table", json={**_TABLE_BODY, "scene_id": "body"})
    assert resp.status_code == 422
    assert "path-id" in resp.json()["detail"]


def test_generic_render_of_composed_json_loses_the_composition_handlers() -> None:
    # The defect (owner 'rest', HubDisplay.replace_scene): pushing a composition as
    # wire JSON through the generic render decodes it with built-in handlers only —
    # the constructed filter handlers are not wire-expressible. The /table route is
    # the fix; this pins the contrast that motivates it.
    roots = TableComposition.build(
        TableCompositionSpec(
            columns=("ID", "Status"),
            rows=(("1", "open"),),
            filters=({"type": "search", "column": [0]},),
        )
    )
    wire = [cast("WireElement", r).to_dict() for r in roots]
    store = HubDisplay()
    client = make_client(store=store)
    resp = client.put("/scenes/issues", json={"scene_id": "issues", "elements": wire})
    assert resp.status_code == 200
    search = cast(
        "AbcElement", store.resolve(SceneId("issues"), ElementId("table-search"))
    )
    # The constructed SearchFilterHandler was stripped on decode — dead chrome.
    assert search.handler_count(ValueChanged) < 2
