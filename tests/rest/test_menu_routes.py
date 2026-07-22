"""The Hub-owned menu routes over the real facade through TestClient."""

from __future__ import annotations

from ._fakes import make_client


def test_list_menus_is_empty_initially() -> None:
    client = make_client()
    resp = client.get("/menus")
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok", "menus": []}


def test_set_menu_then_list_reflects_it() -> None:
    client = make_client()
    body = {
        "menus": [
            {
                "label": "Tools",
                "items": [{"kind": "action", "id": "run", "label": "Run"}],
            }
        ]
    }
    assert client.put("/menus", json=body).status_code == 200
    listed = client.get("/menus").json()
    assert [m["label"] for m in listed["menus"]] == ["Tools"]


def test_set_menu_rejects_a_malformed_entry_with_422() -> None:
    # An id-less, non-separator action is not a real state; the discriminated
    # MenuEntry rejects it at bind time.
    client = make_client()
    body = {
        "menus": [{"label": "Tools", "items": [{"kind": "action", "label": "Run"}]}]
    }
    assert client.put("/menus", json=body).status_code == 422


def test_register_menu_item() -> None:
    client = make_client()
    resp = client.post("/menus/items", json={"tool_id": "run", "label": "Run"})
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok"}


def test_register_menu_item_rejects_an_empty_id_with_422() -> None:
    client = make_client()
    resp = client.post("/menus/items", json={"tool_id": "", "label": "Run"})
    assert resp.status_code == 422
