"""CompositionBoundary — the one ValueError-to-OpError boundary DES-086 shares."""

from __future__ import annotations

from punt_lux.operations.composition_boundary import CompositionBoundary
from punt_lux.operations.models.common import OpError


def test_compose_or_reject_returns_the_composed_value_on_success() -> None:
    assert CompositionBoundary.compose_or_reject(lambda: "c1\x1flocal") == "c1\x1flocal"


def test_compose_or_reject_turns_a_value_error_into_an_invalid_request_op_error() -> (
    None
):
    def _raise() -> str:
        msg = "local id must be a non-empty, non-blank id"
        raise ValueError(msg)

    result = CompositionBoundary.compose_or_reject(_raise)

    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert result.reason == "local id must be a non-empty, non-blank id"
