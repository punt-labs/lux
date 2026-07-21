"""The display-mode routes over the real facade through TestClient."""

from __future__ import annotations

from pathlib import Path

from ._fakes import make_client


def test_read_display_mode_defaults_to_off(tmp_path: Path) -> None:
    client = make_client()
    resp = client.get("/display-mode", params={"repo": str(tmp_path)})
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok", "mode": "off"}


def test_read_display_mode_rejects_a_relative_repo_with_422() -> None:
    # The operation validates the repo and returns invalid_request; the route
    # maps that to 422, the same status FastAPI gives a malformed body.
    client = make_client()
    resp = client.get("/display-mode", params={"repo": "relative/path"})
    assert resp.status_code == 422
    assert "absolute" in resp.json()["detail"]


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    client = make_client()
    written = client.put("/display-mode", json={"mode": "on", "repo": str(tmp_path)})
    assert written.status_code == 200
    assert written.json() == {"kind": "ok", "mode": "on"}
    read = client.get("/display-mode", params={"repo": str(tmp_path)})
    assert read.json() == {"kind": "ok", "mode": "on"}


def test_write_rejects_a_bad_mode_with_422(tmp_path: Path) -> None:
    client = make_client()
    resp = client.put("/display-mode", json={"mode": "maybe", "repo": str(tmp_path)})
    assert resp.status_code == 422


def test_write_rejects_a_relative_repo_with_422() -> None:
    # The write path once trusted its repo — a malformed one reached the config
    # writer and could 500. Now the request model validates repo like the read
    # path, so FastAPI binding rejects it with a loc-named 422 before the write.
    client = make_client()
    resp = client.put("/display-mode", json={"mode": "on", "repo": "relative/path"})
    assert resp.status_code == 422
    detail = resp.json()["detail"][0]
    assert detail["loc"][-1] == "repo"
    assert "absolute" in detail["msg"]


def test_write_rejects_an_empty_repo_with_422() -> None:
    client = make_client()
    resp = client.put("/display-mode", json={"mode": "on", "repo": ""})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"][-1] == "repo"


def test_write_rejects_a_nonexistent_absolute_repo_with_422() -> None:
    # An absolute path that does not exist is not a project; the repo validator
    # names the field and says so.
    client = make_client()
    resp = client.put(
        "/display-mode", json={"mode": "on", "repo": "/no/such/lux/project"}
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"][0]
    assert detail["loc"][-1] == "repo"
    assert "does not exist" in detail["msg"]


def test_write_rejects_an_absent_repo_field_with_422() -> None:
    # Omitting repo entirely is FastAPI's own "field required" binding rejection.
    client = make_client()
    resp = client.put("/display-mode", json={"mode": "on"})
    assert resp.status_code == 422
    detail = resp.json()["detail"][0]
    assert detail["loc"][-1] == "repo"
    assert detail["type"] == "missing"


def test_write_faults_with_502_on_config_io_failure(tmp_path: Path) -> None:
    # The repo is a valid directory (passes the bind-time repo rule), but its
    # .punt-labs is a file, so writing the config raises an OSError the store
    # maps to a fault → 502. Previously this crashed the tool.
    (tmp_path / ".punt-labs").write_text("not a directory")
    client = make_client()
    resp = client.put("/display-mode", json={"mode": "on", "repo": str(tmp_path)})
    assert resp.status_code == 502
