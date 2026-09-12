"""The reserved-topic namespace value object."""

from __future__ import annotations

from punt_lux.domain.hub.menu_event import MENU_TOPIC
from punt_lux.operations.models import OpError
from punt_lux.operations.reserved_topics import RESERVED_TOPICS, ReservedTopics


def test_covers_reserved_prefix_and_menu_topic() -> None:
    assert RESERVED_TOPICS.covers("lux.menu")
    assert RESERVED_TOPICS.covers("lux.anything.future")
    assert RESERVED_TOPICS.covers(MENU_TOPIC)


def test_does_not_cover_agent_topics() -> None:
    assert not RESERVED_TOPICS.covers("openTicket")
    assert not RESERVED_TOPICS.covers("work.saved")
    # A topic that merely contains, but does not start with, the prefix.
    assert not RESERVED_TOPICS.covers("app.lux.menu")


def test_menu_topic_lives_in_the_reserved_namespace() -> None:
    # The Hub's own menu delivery constant must stay inside the namespace the
    # public entry points close, or the two would drift and a genuine click
    # topic could become subscribable/publishable.
    assert RESERVED_TOPICS.covers(MENU_TOPIC)


def test_rejection_is_an_invalid_request_naming_the_topic() -> None:
    err = RESERVED_TOPICS.rejection("lux.menu")
    assert isinstance(err, OpError)
    assert err.code == "invalid_request"
    assert "lux.menu" in err.reason
    assert "reserved" in err.reason


def test_default_prefix_is_lux() -> None:
    assert ReservedTopics() == RESERVED_TOPICS
    assert ReservedTopics().covers("lux.x")
