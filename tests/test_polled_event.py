"""``PolledEvent`` is the topic-bearing envelope for ``poll_event`` results.

Subscribers that follow multiple topics on the same connection need
both the topic and the payload to disambiguate fan-outs. ``PolledEvent``
carries both fields and is frozen so renderers and tests can compare
events by value.
"""

from __future__ import annotations

import pytest

from punt_lux.polled_event import PolledEvent


def test_polled_event_exposes_topic_and_payload() -> None:
    """``PolledEvent`` carries both ``topic`` and ``payload`` verbatim."""
    event = PolledEvent(topic="work.saved", payload={"id": "save_btn"})

    assert event.topic == "work.saved"
    assert event.payload == {"id": "save_btn"}


def test_polled_event_is_frozen() -> None:
    """The dataclass is immutable so listeners cannot mutate queued events."""
    event = PolledEvent(topic="t", payload={})

    with pytest.raises(AttributeError):
        event.topic = "other"  # type: ignore[misc]  # frozen


def test_polled_event_equality_is_by_value() -> None:
    """Two events with the same topic and payload compare equal."""
    a = PolledEvent(topic="t", payload={"k": "v"})
    b = PolledEvent(topic="t", payload={"k": "v"})

    assert a == b
