"""The service routes — register what a client serves, and list who serves what.

``relay`` has no route: it is the one call every service's own routes make, and
there is no generic "call any service" route (DES-107).
"""

from __future__ import annotations

from ._fakes import make_client


def test_register_succeeds_for_an_identified_listening_caller() -> None:
    client = make_client(listening=True)

    resp = client.post("/services", json={"service": "terminal"})

    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok"}


def test_register_then_list_names_the_service_and_the_declared_host() -> None:
    client = make_client(listening=True)
    client.post("/services", json={"service": "terminal"})

    listed = client.get("/services").json()

    assert listed == {
        "kind": "ok",
        "services": [{"service": "terminal", "host": "test-host"}],
    }


def test_register_without_a_listen_leg_is_refused_with_403() -> None:
    client = make_client()

    resp = client.post("/services", json={"service": "terminal"})

    assert resp.status_code == 403
    assert resp.json()["code"] == "push_required"


def test_register_without_identity_is_challenged() -> None:
    client = make_client(identity={}, listening=True)

    resp = client.post("/services", json={"service": "terminal"})

    assert resp.status_code == 401


def test_register_rejects_a_malformed_service_name_with_422() -> None:
    client = make_client(listening=True)

    assert client.post("/services", json={"service": ""}).status_code == 422
    assert client.post("/services", json={"service": "Not A Name"}).status_code == 422


def test_list_of_nothing_registered_is_empty() -> None:
    client = make_client(listening=True)

    assert client.get("/services").json() == {"kind": "ok", "services": []}


def test_list_without_identity_is_challenged() -> None:
    client = make_client(identity={}, listening=True)

    assert client.get("/services").status_code == 401
