"""The four ways a relayed call ends, and the refusal to enter a busy provider."""

from __future__ import annotations

import pytest

from punt_lux.hub.call_outcomes import (
    Lost,
    ProviderBusyError,
    Refused,
    Replied,
    TimedOut,
)


def test_outcomes_compare_by_value() -> None:
    assert Replied({"a": 1}) == Replied({"a": 1})
    assert Refused("fault", "x") == Refused("fault", "x")
    assert TimedOut() == TimedOut()
    assert Lost() == Lost()
    assert Replied({}) != Replied({"a": 1})


def test_a_refusal_is_frozen_so_it_is_hashable() -> None:
    assert hash(Refused("fault", "x")) == hash(Refused("fault", "x"))


def test_a_busy_provider_is_an_error_naming_it() -> None:
    with pytest.raises(ProviderBusyError, match="busy"):
        raise ProviderBusyError("provider busy")
