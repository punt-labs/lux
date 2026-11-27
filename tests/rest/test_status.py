"""The one OpError -> HTTP mapping: total coverage and pass-through behavior."""

from __future__ import annotations

from typing import get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from punt_lux.rest.op_error_response import OpFailureError
from punt_lux.rest.status import HttpErrorMap
from punt_lux.wire.operations.common import OpError, OpErrorCode
from punt_lux.wire.operations.scene_results import SceneShown

_EXPECTED = {
    "invalid_request": 422,
    "identification_required": 401,
    "push_required": 403,
    "not_found": 404,
    "rejected": 409,
    "fault": 502,
    "display_unavailable": 503,
    "timeout": 504,
    "provider_unavailable": 503,
    "provider_lost": 502,
}


def test_every_op_error_code_has_a_status() -> None:
    # Enumerate the closed Literal, not a hand-copied list: a new code added to
    # OpErrorCode with no mapping makes status_for raise KeyError here, so the
    # gap fails loud rather than degrading a route to an unhandled 500.
    errors = HttpErrorMap()
    for code in get_args(OpErrorCode):
        assert errors.status_for(code) == _EXPECTED[code]


def test_mapping_covers_exactly_the_declared_codes() -> None:
    assert set(get_args(OpErrorCode)) == set(_EXPECTED)


def test_respond_passes_a_success_result_through() -> None:
    errors = HttpErrorMap()
    shown = SceneShown(scene_id="s1")
    assert errors.respond(shown) is shown


@pytest.mark.parametrize(("code", "status"), sorted(_EXPECTED.items()))
def test_respond_raises_the_mapped_status_with_the_reason(
    code: str, status: int
) -> None:
    errors = HttpErrorMap()
    with pytest.raises(OpFailureError) as exc:
        errors.respond(OpError(code=code, reason="boom"))  # type: ignore[arg-type]
    assert exc.value.status == status
    assert exc.value.code == code
    assert exc.value.reason == "boom"


def test_a_relayed_error_carries_its_code_in_the_body_beside_the_reason() -> None:
    app = FastAPI()
    HttpErrorMap().install(app)

    @app.get("/relay")
    def relay() -> None:
        HttpErrorMap().respond(
            OpError(code="provider_lost", reason="terminal on okinos was lost")
        )

    response = TestClient(app).get("/relay")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "terminal on okinos was lost",
        "code": "provider_lost",
    }


@pytest.mark.parametrize(("code", "status"), sorted(_EXPECTED.items()))
def test_every_error_body_names_its_code(code: str, status: int) -> None:
    app = FastAPI()
    HttpErrorMap().install(app)

    @app.get("/e")
    def error() -> None:
        HttpErrorMap().respond(OpError(code=code, reason="boom"))  # type: ignore[arg-type]

    body = TestClient(app).get("/e").json()

    assert body == {"detail": "boom", "code": code}
