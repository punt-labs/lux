"""A credit window conserves its initial capacity without redundant state."""

from __future__ import annotations

import pytest

from punt_lux.pty.credit import CreditWindow


def test_empty_window_can_fill_and_acknowledge_its_entire_capacity() -> None:
    window = CreditWindow(1)
    assert (window.available, window.inflight) == (1, 0)
    window.send(1)
    assert (window.available, window.inflight) == (0, 1)
    window.acknowledge(1)
    assert (window.available, window.inflight) == (1, 0)


@pytest.mark.parametrize("capacity", [0, -1])
def test_nonpositive_capacity_is_rejected(capacity: int) -> None:
    with pytest.raises(ValueError, match="capacity must be positive"):
        CreditWindow(capacity)


@pytest.mark.parametrize("amount", [-1, 0, 2])
def test_invalid_send_and_acknowledgment_preserve_credit(amount: int) -> None:
    window = CreditWindow(1)
    with pytest.raises(ValueError, match="send exceeds"):
        window.send(amount)
    assert (window.available, window.inflight) == (1, 0)
    window.send(1)
    with pytest.raises(ValueError, match="credit exceeds"):
        window.acknowledge(amount)
    assert (window.available, window.inflight) == (0, 1)
