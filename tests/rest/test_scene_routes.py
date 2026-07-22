"""The scene and client routes over the real facade through TestClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from punt_lux.operations.display_reply import DisplayReplied

from ._fakes import StubPort, make_client

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from httpx import Response

_TEXT = {"kind": "text", "id": "t1", "content": "hi"}


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


def test_list_scenes_reflects_a_rendered_scene() -> None:
    client = make_client()
    _render(client, "alpha")
    body = client.get("/scenes").json()
    assert [s["scene_id"] for s in body["scenes"]] == ["alpha"]
    assert body["scenes"][0]["owners"] == ["rest-test"]


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
