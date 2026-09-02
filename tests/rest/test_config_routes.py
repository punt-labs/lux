"""The display-mode route over the real facade through TestClient.

Writing moved out of the Hub entirely (DES-088): the CLI writes
``DisplayModeStore`` directly (``cli/display.py``), so ``PUT /display-mode``
no longer exists -- only the read route is left to test here.
"""

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
