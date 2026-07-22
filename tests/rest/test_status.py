"""The one OpError -> HTTP mapping: total coverage and pass-through behavior."""

from __future__ import annotations

from typing import get_args

import pytest
from fastapi import HTTPException

from punt_lux.operations.models.common import OpError, OpErrorCode
from punt_lux.operations.models.scene_results import SceneShown
from punt_lux.rest.status import HttpErrorMap

_EXPECTED = {
    "invalid_request": 422,
    "not_found": 404,
    "rejected": 409,
    "fault": 502,
    "display_unavailable": 503,
    "timeout": 504,
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
    with pytest.raises(HTTPException) as exc:
        errors.respond(OpError(code=code, reason="boom"))  # type: ignore[arg-type]
    assert exc.value.status_code == status
    assert exc.value.detail == "boom"
