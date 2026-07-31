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


def test_register_callback_succeeds_for_an_identified_listening_caller() -> None:
    client = make_client(listening=True)  # identity headers plus a live listen leg
    resp = client.post(
        "/menus/callbacks", json={"callback": {"id": "beads", "label": "Beads"}}
    )
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok"}


def test_register_callback_then_list_shows_the_session_submenu() -> None:
    client = make_client(listening=True)
    client.post(
        "/menus/callbacks", json={"callback": {"id": "beads", "label": "Beads"}}
    )
    listed = client.get("/menus").json()
    # The caller identified as rest-test in /w/lux; its submenu names the repo.
    assert [m["label"] for m in listed["menus"]] == ["rest-test — /w/lux"]


def test_register_callback_without_a_listen_leg_is_refused_with_403() -> None:
    # A one-shot REST caller can never be told its menu item was clicked, so it may
    # not own one. 403, not 401: the caller is perfectly well named, and no header
    # it could add would make its connection deliverable.
    client = make_client()  # identified, but holding no listen leg
    resp = client.post(
        "/menus/callbacks", json={"callback": {"id": "beads", "label": "Beads"}}
    )
    assert resp.status_code == 403
    assert "listen leg" in resp.json()["detail"]


def test_register_callback_without_identity_is_challenged() -> None:
    # On REST the owning scope is resolved from the headers as a dependency, so an
    # unidentified request is challenged before any operation — and therefore
    # before the push gate — whether or not a leg is held.
    client = make_client(identity={}, listening=True)
    resp = client.post(
        "/menus/callbacks", json={"callback": {"id": "beads", "label": "Beads"}}
    )
    assert resp.status_code == 401


def test_register_callback_rejects_an_empty_id_with_422() -> None:
    client = make_client(listening=True)
    resp = client.post(
        "/menus/callbacks", json={"callback": {"id": "", "label": "Beads"}}
    )
    assert resp.status_code == 422
