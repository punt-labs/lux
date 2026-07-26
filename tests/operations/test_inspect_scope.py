"""``InspectScope`` — the proxied-fact request flags an inspection carries."""

from __future__ import annotations

import pytest

from punt_lux.operations.models.inspect_scope import InspectScope


def test_defaults_request_neither_fact() -> None:
    scope = InspectScope()
    assert not scope.want_mirror
    assert not scope.want_geometry


def test_flags_are_set_independently() -> None:
    assert InspectScope(want_geometry=True).want_geometry
    assert not InspectScope(want_geometry=True).want_mirror
    assert InspectScope(want_mirror=True).want_mirror
    assert not InspectScope(want_mirror=True).want_geometry


def test_scope_is_frozen() -> None:
    scope = InspectScope()
    with pytest.raises((AttributeError, TypeError, ValueError)):
        scope.want_geometry = True
