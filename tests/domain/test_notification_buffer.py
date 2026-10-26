"""NotificationBuffer -- what a patch in progress has not yet announced."""

from __future__ import annotations

from punt_lux.domain.notification_buffer import NotificationBuffer


def test_outside_a_patch_nothing_is_buffered() -> None:
    buffer = NotificationBuffer()

    assert buffer.record("rows") is False


def test_inside_a_patch_a_property_is_buffered_until_the_patch_commits() -> None:
    buffer = NotificationBuffer()
    buffer.begin()

    assert buffer.record("rows") is True
    assert buffer.take() == ["rows"]


def test_taking_what_was_buffered_ends_the_patch() -> None:
    buffer = NotificationBuffer()
    buffer.begin()
    buffer.record("rows")
    buffer.take()

    assert buffer.record("label") is False


def test_a_failed_patch_announces_nothing_and_ends() -> None:
    buffer = NotificationBuffer()
    buffer.begin()
    buffer.record("rows")

    buffer.discard()

    assert (buffer.record("label"), buffer.take()) == (False, [])


def test_a_property_flagged_twice_is_buffered_twice_for_the_announcer_to_merge() -> (
    None
):
    buffer = NotificationBuffer()
    buffer.begin()
    for prop in ("rows", "selected", "rows"):
        buffer.record(prop)

    assert buffer.take() == ["rows", "selected", "rows"]
