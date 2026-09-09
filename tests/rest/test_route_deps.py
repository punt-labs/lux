"""RouteDeps -- the (ops, errors) bundle DisplayRoutes/FrameRoutes take."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from punt_lux.rest.route_deps import RouteDeps
from punt_lux.rest.status import HttpErrorMap

from ._fakes import ForbiddenPort, make_facade


def test_fields_round_trip() -> None:
    ops, errors = make_facade(display_port=ForbiddenPort()), HttpErrorMap()
    deps = RouteDeps(ops, errors)
    assert deps.ops is ops
    assert deps.errors is errors


def test_is_frozen() -> None:
    deps = RouteDeps(make_facade(display_port=ForbiddenPort()), HttpErrorMap())
    with pytest.raises(FrozenInstanceError):
        deps.errors = HttpErrorMap()  # type: ignore[misc]  # proving frozen=True raises
