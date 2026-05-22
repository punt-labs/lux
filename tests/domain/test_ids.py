"""Verify ClientId / SceneId / ElementId carry identity through the type system."""

from __future__ import annotations

from punt_lux.domain import ClientId, ElementId, SceneId


def test_ids_are_distinct_newtypes() -> None:
    """NewType ids are distinct at type-check time and act as str at runtime."""
    assert ClientId("c1") == "c1"
    assert SceneId("s1") == "s1"
    assert ElementId("e1") == "e1"


def test_ids_round_trip_through_str() -> None:
    """NewType instances can be coerced back to str by callers at wire boundaries."""
    cid = ClientId("alice")
    sid = SceneId("scene-1")
    eid = ElementId("btn-1")
    assert str(cid) == "alice"
    assert str(sid) == "scene-1"
    assert str(eid) == "btn-1"
