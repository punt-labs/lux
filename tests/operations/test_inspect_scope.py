"""``InspectScope`` — the proxied-fact request flag that an inspection carries."""

from __future__ import annotations

import pytest

from punt_lux.operations.models.inspect_scope import InspectScope


def test_default_requests_no_fact() -> None:
    scope = InspectScope()
    assert not scope.want_geometry


def test_want_geometry_can_be_set() -> None:
    assert InspectScope(want_geometry=True).want_geometry


def test_scope_is_frozen() -> None:
    scope = InspectScope()
    with pytest.raises((AttributeError, TypeError, ValueError)):
        scope.want_geometry = True
